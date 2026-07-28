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

import json
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

BASE_URL = "http://127.0.0.1:8765"

_pass = 0
_fail = 0


def call(method: str, path: str, token: str | None = None, body: dict | None = None):
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

step("6d. Catalog: databases / categories / components / search")
status, dbs = call("GET", "/catalog/databases", token=TOKEN)
ok("GET /catalog/databases -> 200", status == 200 and dbs.get("count", 0) > 0)
status, cats = call("GET", "/catalog/categories", token=TOKEN)
ok("GET /catalog/categories -> 200", status == 200)
status, comps = call("GET", "/catalog/components", token=TOKEN)
ok("GET /catalog/components -> 200", status == 200)
q = urlencode({"q": "steel", "limit": 3})
status, search = call("GET", f"/catalog/search?{q}", token=TOKEN)
ok("GET /catalog/search -> 200, returns items", status == 200 and "items" in search)

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
