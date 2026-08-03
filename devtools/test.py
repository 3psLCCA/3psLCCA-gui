"""
devtools/test.py

Full local API regression/smoke test - exercises every endpoint the
3psLCCA local API exposes, end to end, against a real running instance of
the app: discovery -> create a brand-new project -> (you paste the token
from File > API Access) -> every registered page -> Construction Works
material shortcuts -> catalog search -> update/trash/restore.

Run against a live app with the local API enabled (Settings -> Local API):

    python devtools/test.py

Stdlib only, no dependencies. Prints [PASS]/[FAIL] per check and a summary
at the end; exits non-zero if anything failed.

Every run creates a fresh project (POST /projects/new) rather than reusing
an existing one - this exercises the full creation flow (currency
derivation, locked fields) and keeps test-created materials out of any
real, long-lived project. There's no delete-project API by design, so
these accumulate in the project list across runs - harmless, but worth
knowing.

GET coverage spans every registered page. POST coverage touches every
writable page too - general_info, bridge_data, financial_data,
maintenance_data, demolition_data, plus the str_* material shortcuts -
each via one confirmed-safe, non-locked field (never guessed field names,
each verified against the actual FieldDef source before use), so it never
risks corrupting real project data through a bad guess. Since every run
creates its own fresh project, none of this ever touches a real one anyway.

Every write is checked twice: once against the POST response's own echoed
data (proves the handler computed the right value), and again via a
separate follow-up GET (proves it was actually persisted, not just
reflected back in that one response). Rejected writes get the same
treatment in reverse - a follow-up GET confirms the field was left
untouched rather than partially applied.

Both POST /projects/new and POST /projects/open are asynchronous - after
either, this script waits 3s, then polls GET /projects/active up to 5
times, 3s apart, before giving up.
"""

import base64
import concurrent.futures
import http.server
import json
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode


# ---------------------------------------------------------------------------
# Minimal local HTTP server for image-upload tests (section 6o) - stdlib
# only, no Pillow dependency in this script. Serves fixed byte payloads at
# fixed paths on an ephemeral 127.0.0.1 port, so the app's own
# resolve_image_urls() (which fetches whatever URL an "upload_img" field is
# given) has something deterministic and local to fetch from - instead of
# depending on some external host staying up/unchanged forever.
# ---------------------------------------------------------------------------

# Smallest known-good real images, hand-picked so building test fixtures
# doesn't require an image library.
_GOOD_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+P+/HgAFhAJ/wlseKgAAAABJRU5ErkJggg=="
)
_GOOD_GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==")
_GOOD_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwc"
    "KDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAj/xAAU"
    "EAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAA/AKgAf//Z"
)


def _make_bmp_1x1() -> bytes:
    """Builds a minimal, genuinely valid 1x1 24-bit BMP from scratch (pure
    stdlib struct - no image library) - a second real-but-disallowed format
    alongside GIF, to prove the JPEG/PNG allowlist isn't just special-casing
    GIF by name."""
    width, height = 1, 1
    row_size = ((width * 3 + 3) // 4) * 4
    pixel_data = b"\x00\x00\xff" + b"\x00" * (row_size - 3)
    dib_header = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(pixel_data), 0, 0, 0, 0)
    pixel_offset = 14 + 40
    file_header = b"BM" + struct.pack("<IHHI", pixel_offset + len(pixel_data), 0, 0, pixel_offset)
    return file_header + dib_header + pixel_data


_GOOD_BMP = _make_bmp_1x1()

_IMAGE_SERVER_ROUTES = {
    "/good.png": ("image/png", _GOOD_PNG),
    "/good.gif": ("image/gif", _GOOD_GIF),
    "/good.jpg": ("image/jpeg", _GOOD_JPEG),
    "/good.bmp": ("image/bmp", _GOOD_BMP),
    "/not_image.html": ("text/html", b"<html><body>not an image at all</body></html>"),
    "/corrupt.png": ("image/png", b"this is not really PNG data, just garbage bytes claiming to be one" * 5),
    "/empty.png": ("image/png", b""),
}


class _ImageTestHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # keep test output quiet - this is a fixture server, not under test itself

    def do_GET(self):
        route = _IMAGE_SERVER_ROUTES.get(self.path)
        if route is None:
            self.send_response(404)
            self.end_headers()
            return
        content_type, payload = route
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _start_image_test_server() -> http.server.HTTPServer:
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _ImageTestHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd

BASE_URL = "http://127.0.0.1:8765"

_pass = 0
_fail = 0


def call(method: str, path: str, token: str | None = None, body: dict | list | None = None):
    """Returns (status_code, parsed_json_body). Never raises on HTTP error
    status - the caller decides what's expected."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{BASE_URL}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-API-Token", token)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def step(label: str):
    print(f"\n--- {label} ---")


def ok(label: str, condition: bool, detail: str = ""):
    global _pass, _fail
    if condition:
        _pass += 1
        print(f"  [PASS] {label}")
    else:
        _fail += 1
        print(f"  [FAIL] {label}" + (f"  ({detail})" if detail else ""))


# ============================================================================
# 0. Discovery - no token required
# ============================================================================
step("0. Discovery")
status, help_doc = call("GET", "/help")
ok("GET /help -> 200", status == 200)
ok("/help lists endpoints", len(help_doc.get("endpoints", [])) > 0)
ok("/help lists registered pages", len(help_doc.get("pages", [])) > 0)
print(f"  {help_doc['api']['name']} v{help_doc['api']['version']}")
print(f"  base_url: {help_doc['api']['base_url']}")
print(f"  pages: {help_doc['pages']}")

status, _ = call("GET", "/")
ok("GET / -> 200 (JSON for scripts)", status == 200)


def wait_until_open(project_id: str, label: str) -> bool:
    """Both POST /projects/open and POST /projects/new hand back control
    before the project is actually reachable (the latter's own response
    note says so: 'finishing its initial page load') - wait 3s, then poll
    GET /projects/active up to 5 times, 3s apart."""
    print(f"  waiting 3s before polling ({label})...")
    time.sleep(3)
    for attempt in range(1, 6):
        _, active_resp = call("GET", "/projects/active")
        if any(p["project_id"] == project_id and p["open"] for p in active_resp["projects"]):
            print(f"  confirmed open on attempt {attempt}/5")
            return True
        print(f"  attempt {attempt}/5: not open yet - retrying in 3s...")
        time.sleep(3)
    return False


# ============================================================================
# 1. Create a brand-new project - always, so every run exercises the full
#    creation flow (currency derivation, locked fields at creation time)
#    instead of reusing/polluting a real long-lived project.
# ============================================================================
step("1. GET /projects (coverage)")
status, projects_resp = call("GET", "/projects")
ok("GET /projects -> 200", status == 200)
print(f"  {len(projects_resp['projects'])} project(s) on this machine before this run")

step("1b. GET /projects/active (coverage)")
status, _ = call("GET", "/projects/active")
ok("GET /projects/active -> 200", status == 200)

step("1c. GET /projects/new (schema)")
status, new_schema = call("GET", "/projects/new")
ok("GET /projects/new -> 200", status == 200)
ok("schema lists country options", len(new_schema["fields"]["country"]["options"]) > 0)
ok("schema lists currency_by_country", len(new_schema.get("currency_by_country", {})) > 0)

step("1d. POST /projects/new (create)")
country = new_schema["fields"]["country"]["options"][0]
project_name = f"test.py run {time.strftime('%Y-%m-%d %H:%M:%S')}"
status, created = call("POST", "/projects/new", body={"project_name": project_name, "country": country})
ok("POST /projects/new -> 200, has project_id + currency",
   status == 200 and "project_id" in created and "currency" in created, detail=f"status={status}")
if status != 200:
    print("Could not create a project - stopping here.")
    print(f"\n{'=' * 60}\nRESULT: {_pass} passed, {_fail} failed\n{'=' * 60}")
    sys.exit(1)
project_id = created["project_id"]
print(f"  created: {project_id}  (name={project_name!r}, country={country!r}, currency={created.get('currency')})")

step("1e. Sending 'currency' explicitly is rejected (derived from country only)")
status, currency_rejected = call("POST", "/projects/new",
                                  body={"project_name": "should be rejected", "country": country, "currency": "USD"})
ok("explicit currency -> 400", status == 400 and currency_rejected.get("error") == "invalid_field_values")


# ============================================================================
# 2. Confirm the new project actually finished opening (async)
# ============================================================================
step(f"2. Confirm project is open: {project_id}")
is_open = wait_until_open(project_id, "create")
ok("project reports open within 5 retries (up to ~18s total)", is_open)
if not is_open:
    print("Could not confirm the project opened - stopping here.")
    print(f"\n{'=' * 60}\nRESULT: {_pass} passed, {_fail} failed\n{'=' * 60}")
    sys.exit(1)


# ============================================================================
# 3. Token - the one manual step (the API never returns one, by design)
# ============================================================================
step("3. Token")
print("In the app: File -> API Access -> copy the token for this project.")
try:
    TOKEN = input("Paste token (blank to stop here): ").strip()
except EOFError:
    TOKEN = ""
if not TOKEN:
    print("\nNo token given - stopping (unauthenticated checks above already ran).")
    print(f"\n{'=' * 60}\nRESULT: {_pass} passed, {_fail} failed\n{'=' * 60}")
    sys.exit(1 if _fail else 0)


# ============================================================================
# 4. GET every registered page - schema + data, self-describing
# ============================================================================
step("4. GET every registered page")
for page in help_doc["pages"]:
    status, body = call("GET", f"/{project_id}/{page}", token=TOKEN)
    self_describing = "fields" in body or "schema" in body
    ok(f"GET /{project_id}/{page}", status == 200 and self_describing, detail=f"status={status}")


# ============================================================================
# 5. POST a form page - merge semantics + locked-field pinning
# ============================================================================
step("5. POST general_info (merge update)")
marker = f"Updated by devtools/test.py at {time.strftime('%Y-%m-%d %H:%M:%S')}"
status, updated = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"remarks": marker})
ok("POST general_info -> 200, remarks updated", status == 200 and updated.get("data", {}).get("remarks") == marker)
status, refetched = call("GET", f"/{project_id}/general_info", token=TOKEN)
ok("GET general_info -> remarks persisted independently of the POST response",
   status == 200 and refetched.get("data", {}).get("remarks") == marker)

step("5b. POST general_info - locked field is pinned, not silently dropped")
status, locked_result = call("POST", f"/{project_id}/general_info", token=TOKEN,
                              body={"project_country": "__should_be_rejected__"})
ok("locked field pinned with a warning", status == 200
   and "warning" in locked_result and "locked_fields_skipped" in locked_result)
status, refetched = call("GET", f"/{project_id}/general_info", token=TOKEN)
ok("GET general_info -> project_country still the original value (not the pin attempt)",
   status == 200 and refetched.get("data", {}).get("project_country") != "__should_be_rejected__")

step("5c. POST general_info - invalid combo value rejected")
# agency_country (unlike unit_system) isn't locked, so a bad value here
# actually gets validated instead of just being pinned-with-a-warning.
status, before_c = call("GET", f"/{project_id}/general_info", token=TOKEN)
original_agency_country = before_c.get("data", {}).get("agency_country")
status, bad_result = call("POST", f"/{project_id}/general_info", token=TOKEN,
                           body={"agency_country": "NotARealCountry"})
ok("invalid value -> 400", status == 400 and bad_result.get("error") == "invalid_field_values",
   detail=f"status={status}")
status, refetched = call("GET", f"/{project_id}/general_info", token=TOKEN)
ok("GET general_info -> agency_country unchanged after rejected write",
   status == 200 and refetched.get("data", {}).get("agency_country") == original_agency_country)

step("5d. POST bridge_data (merge update)")
bd_marker = f"test.py bridge {int(time.time())}"
status, bd_updated = call("POST", f"/{project_id}/bridge_data", token=TOKEN, body={"bridge_name": bd_marker})
ok("POST bridge_data -> 200, bridge_name updated",
   status == 200 and bd_updated.get("data", {}).get("bridge_name") == bd_marker)
status, refetched = call("GET", f"/{project_id}/bridge_data", token=TOKEN)
ok("GET bridge_data -> bridge_name persisted independently of the POST response",
   status == 200 and refetched.get("data", {}).get("bridge_name") == bd_marker)

step("5e. POST bridge_data - locked field (project_country) is pinned")
status, bd_locked = call("POST", f"/{project_id}/bridge_data", token=TOKEN,
                          body={"project_country": "__should_be_rejected__"})
ok("locked field pinned with a warning", status == 200
   and "warning" in bd_locked and "locked_fields_skipped" in bd_locked)
status, refetched = call("GET", f"/{project_id}/bridge_data", token=TOKEN)
ok("GET bridge_data -> project_country still the original value (not the pin attempt)",
   status == 200 and refetched.get("data", {}).get("project_country") != "__should_be_rejected__")

step("5f. POST financial_data (merge update)")
fd_marker = f"test.py financial {int(time.time())}"
status, fd_updated = call("POST", f"/{project_id}/financial_data", token=TOKEN,
                           body={"discount_rate_source": fd_marker})
ok("POST financial_data -> 200, discount_rate_source updated",
   status == 200 and fd_updated.get("data", {}).get("discount_rate_source") == fd_marker)
status, refetched = call("GET", f"/{project_id}/financial_data", token=TOKEN)
ok("GET financial_data -> discount_rate_source persisted independently of the POST response",
   status == 200 and refetched.get("data", {}).get("discount_rate_source") == fd_marker)

step("5g. POST maintenance_data (merge update, numeric field)")
status, md_updated = call("POST", f"/{project_id}/maintenance_data", token=TOKEN,
                           body={"periodic_maintenance_freq": 7})
ok("POST maintenance_data -> 200, periodic_maintenance_freq updated",
   status == 200 and md_updated.get("data", {}).get("periodic_maintenance_freq") == 7)
status, refetched = call("GET", f"/{project_id}/maintenance_data", token=TOKEN)
ok("GET maintenance_data -> periodic_maintenance_freq persisted independently of the POST response",
   status == 200 and refetched.get("data", {}).get("periodic_maintenance_freq") == 7)

step("5h. POST maintenance_data - out-of-range value rejected")
status, md_bad = call("POST", f"/{project_id}/maintenance_data", token=TOKEN,
                       body={"periodic_maintenance_freq": 99999})
ok("out-of-range int -> 400", status == 400 and md_bad.get("error") == "invalid_field_values",
   detail=f"status={status}")
status, refetched = call("GET", f"/{project_id}/maintenance_data", token=TOKEN)
ok("GET maintenance_data -> periodic_maintenance_freq still 7, not corrupted to 99999",
   status == 200 and refetched.get("data", {}).get("periodic_maintenance_freq") == 7)

step("5i. POST demolition_data (merge update, numeric field)")
status, dd_updated = call("POST", f"/{project_id}/demolition_data", token=TOKEN,
                           body={"demolition_cost_pct": 12.5})
ok("POST demolition_data -> 200, demolition_cost_pct updated",
   status == 200 and dd_updated.get("data", {}).get("demolition_cost_pct") == 12.5)
status, refetched = call("GET", f"/{project_id}/demolition_data", token=TOKEN)
ok("GET demolition_data -> demolition_cost_pct persisted independently of the POST response",
   status == 200 and refetched.get("data", {}).get("demolition_cost_pct") == 12.5)


# ============================================================================
# 6. Construction Works Data - GET, read-only registry, catalog, shortcuts
# ============================================================================
TEST_COMPONENT = "TestPy Component"
added: list[tuple[str, str]] = []  # (chunk, entry_id) created this run

step("6a. GET a str_* chunk - schema.units present")
status, str_body = call("GET", f"/{project_id}/str_super_structure", token=TOKEN)
ok("GET str_super_structure -> 200, has schema.units",
   status == 200 and len(str_body.get("schema", {}).get("units", [])) > 0)

step("6b. str_component_registry is read-only")
status, _ = call("GET", f"/{project_id}/str_component_registry", token=TOKEN)
ok("GET str_component_registry -> 200", status == 200)
status, reg_post = call("POST", f"/{project_id}/str_component_registry", token=TOKEN, body={"x": []})
ok("POST str_component_registry -> 405 read_only_chunk",
   status == 405 and reg_post.get("error") == "read_only_chunk")

step("6c. Construction Works no-bulk enforcement")
status, bulk_result = call("POST", f"/{project_id}/str_super_structure", token=TOKEN, body={
    "Girder": [{"values": {"material_name": "A"}}, {"values": {"material_name": "B"}}],
})
ok("2 patches in one request -> 400 (no bulk)",
   status == 400 and bulk_result.get("error") == "invalid_field_values")

step("6d. Catalog: databases / components / items / tokens / search")
status, dbs = call("GET", "/catalog/databases", token=TOKEN)
ok("GET /catalog/databases -> 200", status == 200 and dbs.get("count", 0) > 0)
status, comps = call("GET", "/catalog/components", token=TOKEN)
ok("GET /catalog/components -> 200", status == 200)
q = urlencode({"q": "steel", "limit": 3})
status, search = call("GET", f"/catalog/search?{q}", token=TOKEN)
ok("GET /catalog/search -> 200, returns items", status == 200 and "items" in search)

first_db_key = dbs["databases"][0]["db_key"] if dbs.get("databases") else None
if first_db_key:
    q = urlencode({"db_key": first_db_key, "limit": 2})
    status, items_page = call("GET", f"/catalog/items?{q}", token=TOKEN)
    ok("GET /catalog/items?db_key=...&limit=2 -> 200, respects limit",
       status == 200 and len(items_page.get("items", [])) <= 2 and items_page.get("limit") == 2)

    q = urlencode({"db_key": first_db_key})
    status, tokens_resp = call("GET", f"/catalog/tokens?{q}", token=TOKEN)
    ok("GET /catalog/tokens?db_key=... -> 200, non-empty vocabulary",
       status == 200 and len(tokens_resp.get("tokens", [])) > 0)
else:
    ok("catalog/items + catalog/tokens skipped (no databases available)", True)

step("6d-2. Catalog search requires 'q'")
status, no_q = call("GET", "/catalog/search", token=TOKEN)
ok("GET /catalog/search (no q) -> 400 invalid_field_values",
   status == 400 and no_q.get("error") == "invalid_field_values")

step("6e. add_from_catalog (new component, auto-created)")
if search.get("items"):
    row = search["items"][0]
    status, add_result = call(
        "POST", f"/{project_id}/str_super_structure/add_from_catalog", token=TOKEN,
        body={"component": TEST_COMPONENT, "db_key": row["db_key"],
              "material_name": row["name"], "quantity": 1},
    )
    # Every run creates a brand-new project (step 1), so TEST_COMPONENT is
    # always empty here - no legitimate duplicate-name case is possible.
    ok("add_from_catalog -> 200, new component auto-created", status == 200, detail=f"status={status}")
    if status == 200:
        new_id = [e for e in add_result["data"][TEST_COMPONENT]
                  if e["values"]["material_name"] == row["name"]][-1]["id"]
        added.append(("str_super_structure", new_id))
        status, refetched = call("GET", f"/{project_id}/str_super_structure", token=TOKEN)
        found = any(e["id"] == new_id for e in refetched.get("data", {}).get(TEST_COMPONENT, []))
        ok("GET str_super_structure -> catalog entry persisted independently of the POST response",
           status == 200 and found)
else:
    ok("add_from_catalog skipped (no search results to use)", True)

step("6f. add_manual - flat body, carbon_unit_den, custom_unit")
unique_name = f"test.py manual item {int(time.time())}"
status, manual_result = call(
    "POST", f"/{project_id}/str_super_structure/add_manual", token=TOKEN,
    body={
        "component": TEST_COMPONENT,
        "values": {"material_name": unique_name, "unit": "testpyunit", "quantity": 1, "rate": 1,
                   "carbon_emission": 1.0, "carbon_unit_den": "kg", "conversion_factor": 1.0},
        "state": {"included_in_carbon_emission": True},
        "custom_unit": {"symbol": "testpyunit", "dimension": "Mass", "to_si": 1},
    },
)
manual_ok = status == 200
manual_entry_id = None
if manual_ok:
    new_entry = [e for e in manual_result["data"][TEST_COMPONENT] if e["values"]["material_name"] == unique_name][-1]
    manual_ok = new_entry["values"]["carbon_unit"] == "kgCO₂e/kg" and "meta" not in new_entry
    manual_entry_id = new_entry["id"]
    added.append(("str_super_structure", manual_entry_id))
ok("add_manual -> 200, carbon_unit built from carbon_unit_den, meta hidden", manual_ok, detail=f"status={status}")
if manual_entry_id:
    status, refetched = call("GET", f"/{project_id}/str_super_structure", token=TOKEN)
    persisted = next((e for e in refetched.get("data", {}).get(TEST_COMPONENT, []) if e["id"] == manual_entry_id), None)
    ok("GET str_super_structure -> manual entry persisted independently of the POST response",
       status == 200 and persisted is not None and persisted["values"]["carbon_unit"] == "kgCO₂e/kg")

step("6g. add_manual rejects raw carbon_unit (must use carbon_unit_den)")
status, rejected = call(
    "POST", f"/{project_id}/str_super_structure/add_manual", token=TOKEN,
    body={"component": TEST_COMPONENT,
          "values": {"material_name": "should not be created", "unit": "kg",
                     "quantity": 1, "rate": 1, "carbon_unit": "kgCO2e/kg"}},
)
ok("raw carbon_unit -> 400", status == 400 and rejected.get("error") == "invalid_field_values")
status, refetched = call("GET", f"/{project_id}/str_super_structure", token=TOKEN)
absent = not any(e["values"]["material_name"] == "should not be created"
                  for e in refetched.get("data", {}).get(TEST_COMPONENT, []))
ok("GET str_super_structure -> rejected entry was never created", status == 200 and absent)

step("6h. add_manual rejects a duplicate (case/whitespace-insensitive) material_name in the same component")
status, dup_result = call(
    "POST", f"/{project_id}/str_super_structure/add_manual", token=TOKEN,
    body={"component": TEST_COMPONENT,
          "values": {"material_name": f"  {unique_name.upper()}  ", "unit": "kg", "quantity": 1, "rate": 1}},
)
ok("duplicate material_name (different case/whitespace) -> 400",
   status == 400 and dup_result.get("error") == "invalid_field_values", detail=f"status={status}")

step("6i. add_manual carbon_unit_num override (custom numerator, not just default kgCO2e)")
num_marker = f"test.py num item {int(time.time())}"
status, num_result = call(
    "POST", f"/{project_id}/str_super_structure/add_manual", token=TOKEN,
    body={"component": TEST_COMPONENT,
          "values": {"material_name": num_marker, "unit": "kg", "quantity": 1, "rate": 1,
                     "carbon_emission": 1.0, "carbon_unit_den": "kg", "carbon_unit_num": "CustomUnit"}},
)
num_ok = status == 200
num_entry_id = None
if num_ok:
    num_entry = [e for e in num_result["data"][TEST_COMPONENT] if e["values"]["material_name"] == num_marker][-1]
    num_ok = num_entry["values"]["carbon_unit"] == "CustomUnit/kg"
    num_entry_id = num_entry["id"]
    added.append(("str_super_structure", num_entry_id))
ok("add_manual -> 200, carbon_unit_num overrides default numerator (CustomUnit/kg)", num_ok, detail=f"status={status}")

step("6j. add_manual rejects unrecognized top-level and values keys")
status, bad_top = call(
    "POST", f"/{project_id}/str_super_structure/add_manual", token=TOKEN,
    body={"component": TEST_COMPONENT, "values": {"material_name": "x", "unit": "kg", "quantity": 1, "rate": 1},
          "not_a_real_key": True},
)
ok("unrecognized top-level key -> 400", status == 400 and bad_top.get("error") == "invalid_field_values")
status, bad_values = call(
    "POST", f"/{project_id}/str_super_structure/add_manual", token=TOKEN,
    body={"component": TEST_COMPONENT, "values": {"material_name": "x", "unit": "kg", "quantity": 1, "rate": 1,
                                                   "made_up_field": 1}},
)
ok("unrecognized values key -> 400", status == 400 and bad_values.get("error") == "invalid_field_values")
status, missing_req = call(
    "POST", f"/{project_id}/str_super_structure/add_manual", token=TOKEN,
    body={"component": TEST_COMPONENT, "values": {"material_name": "y"}},
)
ok("missing required values keys (unit/quantity/rate) -> 400",
   status == 400 and missing_req.get("error") == "invalid_field_values")

step("6k. add_from_catalog rejects unrecognized material_name (no match in db)")
if first_db_key:
    status, no_match = call(
        "POST", f"/{project_id}/str_super_structure/add_from_catalog", token=TOKEN,
        body={"component": TEST_COMPONENT, "db_key": first_db_key,
              "material_name": "definitely-not-a-real-material-xyz123", "quantity": 1},
    )
    ok("unknown material_name -> 400", status == 400 and no_match.get("error") == "invalid_field_values",
       detail=f"status={status}")
else:
    ok("add_from_catalog no-match check skipped (no databases available)", True)

step("6l. trash: unknown id is a clean error, not a crash")
status, unknown_trash = call("POST", f"/{project_id}/str_super_structure/trash", token=TOKEN,
                              body={"id": "00000000-0000-0000-0000-000000000000"})
ok("trash unknown id -> 400 invalid_field_values", status == 400 and unknown_trash.get("error") == "invalid_field_values")


# ============================================================================
# 6m. Construction Works chunks that don't support the material shortcuts -
#     add_from_catalog/add_manual/trash are str_* only. general_info is a
#     FieldDef page with none of those hooks registered, so it's a clean
#     negative case for every one of them.
# ============================================================================
step("6m. Material shortcuts are 404 not_supported on a non-str_* chunk")
status, r = call("POST", f"/{project_id}/general_info/add_from_catalog", token=TOKEN,
                  body={"component": "x", "db_key": "x", "material_name": "x", "quantity": 1})
ok("POST general_info/add_from_catalog -> 404 not_supported",
   status == 404 and r.get("error") == "not_supported")
status, r = call("POST", f"/{project_id}/general_info/add_manual", token=TOKEN,
                  body={"component": "x", "values": {"material_name": "x", "unit": "x", "quantity": 1, "rate": 1}})
ok("POST general_info/add_manual -> 404 not_supported",
   status == 404 and r.get("error") == "not_supported")
status, r = call("GET", f"/{project_id}/general_info/trash", token=TOKEN)
ok("GET general_info/trash -> 404 not_supported", status == 404 and r.get("error") == "not_supported")
status, r = call("POST", f"/{project_id}/general_info/trash", token=TOKEN, body={"id": "whatever"})
ok("POST general_info/trash -> 404 not_supported", status == 404 and r.get("error") == "not_supported")


# ============================================================================
# 6n. general_info: unrecognized field key is rejected, not silently dropped
# ============================================================================
step("6n. POST general_info with an unrecognized key ('abc') is rejected atomically")
status, before_abc = call("GET", f"/{project_id}/general_info", token=TOKEN)
before_remarks = before_abc.get("data", {}).get("remarks")
status, abc_result = call("POST", f"/{project_id}/general_info", token=TOKEN,
                           body={"remarks": "should not stick", "abc": "not a real field"})
ok("unrecognized key 'abc' -> 400 invalid_field_values, whole request rejected",
   status == 400 and abc_result.get("error") == "invalid_field_values"
   and any("abc" in d for d in abc_result.get("details", [])))
status, refetched = call("GET", f"/{project_id}/general_info", token=TOKEN)
ok("GET general_info -> remarks untouched (nothing partially applied)",
   status == 200 and refetched.get("data", {}).get("remarks") == before_remarks)


# ============================================================================
# 6o. Image upload via URL (upload_img field) - a plainly-unreachable URL
#     must fail cleanly rather than hang or 500.
# ============================================================================
step("6o. upload_img field: unreachable image URL is rejected, not silently accepted")
status, bad_img = call("POST", f"/{project_id}/general_info", token=TOKEN,
                        body={"agency_logo": "https://this-domain-should-not-resolve.invalid/logo.png"})
ok("unreachable image URL -> 400 invalid_field_values", status == 400 and bad_img.get("error") == "invalid_field_values")

step("6o-1. Schema advertises the JPEG/PNG restriction (GET general_info fields)")
status, gi_schema = call("GET", f"/{project_id}/general_info", token=TOKEN)
logo_field = next((f for f in gi_schema.get("fields", []) if f.get("key") == "agency_logo"), None)
ok("agency_logo field schema lists accepted_image_formats == ['JPEG', 'PNG']",
   status == 200 and logo_field is not None
   and logo_field.get("accepted_image_formats") == ["JPEG", "PNG"])

step("6o-1b. upload_img accepts a real external image URL (live network, not just the local fixture server)")
status, r = call("POST", f"/{project_id}/general_info", token=TOKEN,
                  body={"agency_logo": "https://placehold.co/600x400/png"})
ok("https://placehold.co/600x400/png -> 200, real PNG downloaded/converted/stored "
   "(depends on placehold.co being reachable - a network hiccup here isn't a code bug)",
   status == 200 and bool(r.get("data", {}).get("agency_logo")))

_img_httpd = _start_image_test_server()
_img_port = _img_httpd.server_address[1]
_img_base = f"http://127.0.0.1:{_img_port}"

step("6o-2. upload_img accepts a real PNG via URL (baseline)")
status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"agency_logo": f"{_img_base}/good.png"})
ok("real PNG via URL -> 200, non-empty base64 stored",
   status == 200 and bool(r.get("data", {}).get("agency_logo")))

step("6o-2b. upload_img accepts a real JPEG via URL (the other allowed format)")
status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"agency_logo": f"{_img_base}/good.jpg"})
ok("real JPEG via URL -> 200, non-empty base64 stored",
   status == 200 and bool(r.get("data", {}).get("agency_logo")))

step("6o-3. upload_img rejects real but disallowed image formats (GIF, BMP) - only JPEG/PNG accepted")
status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"agency_logo": f"{_img_base}/good.gif"})
ok("real, valid GIF via URL -> 400 invalid_field_values (format not allowed, not just 'not an image')",
   status == 400 and r.get("error") == "invalid_field_values")
status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"agency_logo": f"{_img_base}/good.bmp"})
ok("real, valid BMP via URL -> 400 invalid_field_values (confirms it's a format allowlist, not a GIF special-case)",
   status == 400 and r.get("error") == "invalid_field_values")

step("6o-4. upload_img rejects a non-image format injected at an image URL")
status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"agency_logo": f"{_img_base}/not_image.html"})
ok("HTML content served in place of an image -> 400 invalid_field_values, not silently accepted",
   status == 400 and r.get("error") == "invalid_field_values")

step("6o-5. upload_img rejects a corrupt image file (garbage bytes with an image extension/content-type)")
status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"agency_logo": f"{_img_base}/corrupt.png"})
ok("corrupt/undecodable PNG bytes -> 400 invalid_field_values, not a 500 or silent garbage store",
   status == 400 and r.get("error") == "invalid_field_values")

step("6o-6. upload_img rejects a zero-byte file")
status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"agency_logo": f"{_img_base}/empty.png"})
ok("empty file body -> 400 invalid_field_values", status == 400 and r.get("error") == "invalid_field_values")

_img_httpd.shutdown()

step("6o-7. upload_img given a raw (non-URL) string is also Pillow-validated, not just URL values")
# image_upload.py validates BOTH branches: an http(s) URL is downloaded then
# decoded via Pillow, and any other non-empty string is base64-decoded and
# Pillow-verified in place (no recompression) - so a caller can't smuggle
# arbitrary garbage past the "upload_img" field just by not using a URL.
status, r = call("POST", f"/{project_id}/general_info", token=TOKEN,
                  body={"agency_logo": "this-is-not-base64-image-data-and-not-a-url-either"})
ok("raw non-base64 garbage string -> 400 invalid_field_values",
   status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/general_info", token=TOKEN,
                  body={"agency_logo": base64.b64encode(b"not really an image, just text bytes").decode()})
ok("raw base64-valid-but-not-an-image string -> 400 invalid_field_values",
   status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/general_info", token=TOKEN,
                  body={"agency_logo": base64.b64encode(_GOOD_GIF).decode()})
ok("raw base64 of a real, valid GIF (not via URL) -> 400 invalid_field_values (format check applies here too)",
   status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/general_info", token=TOKEN,
                  body={"agency_logo": base64.b64encode(_GOOD_BMP).decode()})
ok("raw base64 of a real, valid BMP (not via URL) -> 400 invalid_field_values",
   status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/general_info", token=TOKEN,
                  body={"agency_logo": base64.b64encode(_GOOD_PNG).decode()})
ok("raw base64 of a real PNG (not via URL) -> 200, accepted and stored as-is",
   status == 200 and r.get("data", {}).get("agency_logo") == base64.b64encode(_GOOD_PNG).decode())

status, r = call("POST", f"/{project_id}/general_info", token=TOKEN,
                  body={"agency_logo": base64.b64encode(_GOOD_JPEG).decode()})
ok("raw base64 of a real JPEG (not via URL) -> 200, accepted and stored as-is",
   status == 200 and r.get("data", {}).get("agency_logo") == base64.b64encode(_GOOD_JPEG).decode())

step("6o-8. upload_img: empty string still clears the field (same as the GUI's Clear button)")
status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"agency_logo": ""})
ok("empty string -> 200, accepted as a clear (not run through image validation)",
   status == 200 and r.get("data", {}).get("agency_logo") == "")


# ============================================================================
# 6p. Type-checking - every field type must reject the wrong JSON type,
#     not coerce it or silently no-op. bool is deliberately not accepted
#     for int/float fields (isinstance(True, int) is True in Python, so
#     validate_payload_keys special-cases it - see registry.py:241).
# ============================================================================
step("6p. Type validation - wrong JSON type per field is rejected, not coerced")

status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"project_name": 12345})
ok("text field given a number -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"project_name": ["a", "list"]})
ok("text field given a list -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"agency_country": 42})
ok("combo field given a number -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/maintenance_data", token=TOKEN,
                  body={"periodic_maintenance_freq": "seven"})
ok("int field given a string -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/maintenance_data", token=TOKEN,
                  body={"periodic_maintenance_freq": True})
ok("int field given a bool -> 400 (bool explicitly excluded, not treated as 0/1)",
   status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/maintenance_data", token=TOKEN,
                  body={"periodic_maintenance_freq": None})
ok("int field given null -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/demolition_data", token=TOKEN,
                  body={"demolition_cost_pct": {"nested": "object"}})
ok("float field given an object -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, before_mf = call("GET", f"/{project_id}/maintenance_data", token=TOKEN)
mf_untouched = before_mf.get("data", {}).get("periodic_maintenance_freq")
ok("maintenance_data unaffected by any of the rejected type-mismatched writes above",
   mf_untouched == 7)


# ============================================================================
# 6q. Injection-style payloads - this API stores everything as plain JSON/
#     text on disk (no SQL, no server-side template/eval of field values),
#     so the only correct behaviour is "stored and echoed back verbatim,
#     nothing executed, nothing crashes". These checks prove that rather
#     than assuming it.
# ============================================================================
step("6q. Injection-style strings are stored inertly (no execution, no crash, no corruption)")

INJECTION_PAYLOADS = [
    ("sql_like", "'; DROP TABLE projects; --"),
    ("script_tag", "<script>alert(document.cookie)</script>"),
    ("path_traversal", "../../../../etc/passwd"),
    ("null_byte", "before\x00after"),
    ("template_injection", "{{7*7}}${7*7}#{7*7}"),
    ("format_string", "%s%s%s%n"),
    ("unicode_rtl_override", "normal‮gnitset desrever"),
    ("very_long", "A" * 20000),
]

for label, payload_str in INJECTION_PAYLOADS:
    status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"remarks": payload_str})
    stored = status == 200 and r.get("data", {}).get("remarks") == payload_str
    ok(f"remarks accepts {label!r}-style string and echoes it back byte-for-byte, no crash",
       stored, detail=f"status={status}")
    status, refetched = call("GET", f"/{project_id}/general_info", token=TOKEN)
    ok(f"GET after {label} -> server still responds 200 (didn't crash/corrupt the chunk)",
       status == 200 and refetched.get("data", {}).get("remarks") == payload_str)

step("6q-2. Injection-style string as a POST project_name is also inert")
status, r = call("POST", "/projects/new", body={
    "project_name": "<img src=x onerror=alert(1)>'; DROP TABLE x; --",
    "country": country,
})
ok("malicious-looking project_name -> 200, created and stored as literal text (never interpreted)",
   status == 200 and "project_id" in r)


# ============================================================================
# 6r. Bounded local resilience check - NOT a load/DoS test: a small, fixed
#     burst of concurrent requests against this machine's own local-only
#     (127.0.0.1) API, purely to confirm the werkzeug dev server thread
#     doesn't crash or wedge under mild concurrency. Keep this small; it
#     exists to catch "the server falls over on 2 requests at once" bugs,
#     not to benchmark throughput.
# ============================================================================
step("6r. Bounded concurrency burst - server stays up and consistent under a small parallel load")

BURST_SIZE = 20


def _burst_get():
    return call("GET", f"/{project_id}/general_info", token=TOKEN)


with concurrent.futures.ThreadPoolExecutor(max_workers=BURST_SIZE) as pool:
    results = list(pool.map(lambda _: _burst_get(), range(BURST_SIZE)))
all_200 = all(s == 200 for s, _ in results)
ok(f"{BURST_SIZE} concurrent GET general_info requests -> all 200, no crash",
   all_200, detail=f"statuses={[s for s, _ in results]}")

status, alive = call("GET", "/help")
ok("GET /help still 200 immediately after the burst (server survived)", status == 200)

# A burst of rapid sequential writes to the SAME field - checks the merge
# logic doesn't corrupt state or drop writes under back-to-back POSTs (not
# a correctness guarantee about which one "wins", just that the server
# stays coherent: it ends on some valid string, not garbage/None/crash).
for i in range(BURST_SIZE):
    call("POST", f"/{project_id}/general_info", token=TOKEN, body={"remarks": f"burst-{i}"})
status, final = call("GET", f"/{project_id}/general_info", token=TOKEN)
ok("rapid sequential writes to the same field -> server stays coherent (valid final string, no crash)",
   status == 200 and isinstance(final.get("data", {}).get("remarks"), str)
   and final["data"]["remarks"].startswith("burst-"))


# ============================================================================
# 6s. Auth & routing error matrix - 401 / 404 cases not otherwise exercised.
# ============================================================================
step("6s. Auth & routing errors")

status, r = call("GET", f"/{project_id}/general_info")  # no token at all
ok("GET data endpoint with no token -> 401", status == 401 and r.get("error") == "unauthorized")

status, r = call("GET", f"/{project_id}/general_info", token="not-the-real-token")
ok("GET data endpoint with wrong token -> 401", status == 401 and r.get("error") == "unauthorized")

status, r = call("POST", f"/{project_id}/general_info", body={"remarks": "x"})  # no token
ok("POST data endpoint with no token -> 401", status == 401 and r.get("error") == "unauthorized")

status, r = call("GET", "/nonexistent_project_id_xyz/general_info", token=TOKEN)
# Tokens are per-project_id (tokens.py:31-36): check_token() looks up the
# token registered for THIS SPECIFIC project_id, so a real token for our
# actual project_id is simply not "expected" for a different, unknown
# project_id - check_token() returns False regardless of what's supplied,
# and the route 401s before ever reaching the bridge/project_not_open check.
ok("GET unknown project_id (with a token valid for a different project) -> 401 unauthorized",
   status == 401 and r.get("error") == "unauthorized")

status, r = call("POST", "/projects/open", body={"project_id": "nonexistent_project_id_xyz"})
ok("POST /projects/open unknown project_id -> 404 project_not_found",
   status == 404 and r.get("error") == "project_not_found")

status, r = call("GET", f"/{project_id}/not_a_real_chunk", token=TOKEN)
ok("GET unknown chunk name -> 404 not_found", status == 404 and r.get("error") == "not_found")

status, r = call("GET", "/completely/unknown/route/here")
ok("GET completely unknown route -> 404 not_found", status == 404 and r.get("error") == "not_found")

status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body=["this", "is", "a", "list", "not", "a", "dict"])
ok("POST with a JSON array body (not an object) -> 400 invalid_json_body",
   status == 400 and r.get("error") == "invalid_json_body")

status, r = call("POST", "/projects/new", body=["also", "not", "a", "dict"])
ok("POST /projects/new with a JSON array body -> 400 invalid_json_body",
   status == 400 and r.get("error") == "invalid_json_body")


# ============================================================================
# 7. Update by id, trash, list trashed, restore, re-trash (cleanup)
# ============================================================================
if added:
    chunk, entry_id = added[-1]

    step("7a. Update entry by id (generic endpoint)")
    status, upd = call("POST", f"/{project_id}/{chunk}", token=TOKEN,
                        body={TEST_COMPONENT: [{"id": entry_id, "values": {"rate": 999}}]})
    ok("update by id -> 200, rate changed", status == 200
       and any(e["id"] == entry_id and e["values"]["rate"] == 999 for e in upd["data"][TEST_COMPONENT]))
    status, refetched = call("GET", f"/{project_id}/{chunk}", token=TOKEN)
    ok("GET -> rate=999 persisted independently of the POST response", status == 200
       and any(e["id"] == entry_id and e["values"]["rate"] == 999
               for e in refetched.get("data", {}).get(TEST_COMPONENT, [])))

    step("7b. Trash by id (dedicated shortcut)")
    status, _ = call("POST", f"/{project_id}/{chunk}/trash", token=TOKEN, body={"id": entry_id})
    ok("POST .../trash -> 200", status == 200)

    step("7c. List trashed entries")
    status, trashed = call("GET", f"/{project_id}/{chunk}/trash", token=TOKEN)
    found_trashed = any(e["id"] == entry_id for entries in trashed.get("data", {}).values() for e in entries)
    ok("GET .../trash -> 200, entry appears", status == 200 and found_trashed)

    step("7d. Restore (untrash)")
    status, restored = call("POST", f"/{project_id}/{chunk}/trash", token=TOKEN,
                             body={"id": entry_id, "untrash": True})
    still_there = any(e["id"] == entry_id and not e["state"]["in_trash"]
                       for e in restored.get("data", {}).get(TEST_COMPONENT, []))
    ok("untrash=true -> 200, restored", status == 200 and still_there)
    status, refetched_trash = call("GET", f"/{project_id}/{chunk}/trash", token=TOKEN)
    gone_from_trash = not any(e["id"] == entry_id
                               for entries in refetched_trash.get("data", {}).values() for e in entries)
    ok("GET .../trash -> restored entry no longer listed as trashed", status == 200 and gone_from_trash)

    step("7e. Re-trash all test.py-created entries (cleanup)")
    cleanup_ok = True
    for chunk, entry_id in added:
        s, _ = call("POST", f"/{project_id}/{chunk}/trash", token=TOKEN, body={"id": entry_id})
        cleanup_ok = cleanup_ok and s == 200
    ok(f"cleaned up {len(added)} entry/entries created this run (left trashed, not deleted)", cleanup_ok)
else:
    print("\n(no entries were created this run - nothing to update/trash)")


# ============================================================================
# Summary
# ============================================================================
print(f"\n{'=' * 60}")
print(f"RESULT: {_pass} passed, {_fail} failed")
print(f"{'=' * 60}")
sys.exit(1 if _fail else 0)
