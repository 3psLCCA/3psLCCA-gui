"""
devtools/test apis/general_info.test.py

Focused regression test for the "general_info" chunk of the 3psLCCA local
API - a standalone extract of the general_info-related cases from
devtools/test.py, so this one page's contract (merge semantics, locked
fields, combo/type validation, the upload_img/agency_logo pipeline) can be
exercised on its own without running the full cross-chunk suite.

Run against a live app with the local API enabled (Settings -> Local API):

    python "devtools/test apis/general_info.test.py"

Stdlib only, no dependencies. Prints [PASS]/[FAIL] per check and a summary
at the end; exits non-zero if anything failed.

Creates a fresh project every run (POST /projects/new) - same reasoning as
devtools/test.py: exercises the real creation flow and never touches a
real, long-lived project's data.

Image-upload ordering note: the checks that write a "clearing" empty string
to agency_logo run BEFORE the final real-image writes, so the run ends with
a real, persisted logo (verified via a follow-up GET) - not an empty field.

Verification policy - every state-changing POST is checked twice:
  1. Programmatically, via a follow-up GET (proves the write actually
     persisted, or - for rejected writes - proves nothing changed).
  2. For URL-sourced images specifically, ALSO by a human: Pillow
     recompresses every image that goes through the URL-download path
     (image_utils.py's compress_image() re-encodes it as PNG/JPEG at a
     fixed quality/size), so the base64 that comes back is NOT the
     original bytes - byte-equality doesn't apply there the way it does
     for a raw base64 upload. The script decodes the stored result to a
     file next to this one and asks whoever is running it to actually open
     it and confirm it still looks like the right image, not corrupted or
     blank. Raw (non-URL) base64 uploads are NOT recompressed, so those are
     still checked by exact byte comparison only - no human step needed.

Project/token setup is shared via _common.py in this same folder - see
that module's docstring for the --project-id/--token flags and the
interactive numbered project picker.
"""

import base64
import http.server
import os
import struct
import sys
import threading
import time

from _common import call, step, ok, build_arg_parser, setup_project_and_token, summary

_skip = 0


def get_data(project_id: str, token: str) -> dict:
    """Shorthand for the GET half of a POST->GET verification pair."""
    _, body = call("GET", f"/{project_id}/general_info", token=token)
    return body.get("data", {})


_VISUAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_visual_check")


def _sniff_ext(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    return ".bin"


def visual_confirm(label: str, base64_str: str, expected_hint: str) -> None:
    """Decodes `base64_str` to a file next to this script and asks a human
    to open it and confirm it looks right. Only meaningful for images that
    went through Pillow's recompression (the URL-download path) - a raw
    base64 upload is stored byte-for-byte, so there's nothing new for a
    human to check there that the programmatic GET-verify didn't already
    prove. A yes/no answer feeds into _common's shared pass/fail tally via
    ok() (so it affects the exit code like any other check); a blank
    answer (e.g. running non-interactively) is tracked separately in this
    file's own _skip counter instead, since "no answer given" isn't a
    pass or a fail."""
    global _skip
    os.makedirs(_VISUAL_DIR, exist_ok=True)
    data = base64.b64decode(base64_str)
    path = os.path.join(_VISUAL_DIR, f"{label}{_sniff_ext(data)}")
    with open(path, "wb") as f:
        f.write(data)
    print(f"  -> wrote {path}  ({len(data)} bytes)")
    print(f"     Open it and check: {expected_hint}")
    try:
        answer = input("     Looks correct? [y/n, blank to skip]: ").strip().lower()
    except EOFError:
        answer = ""
    if answer in ("y", "yes"):
        ok(f"visual check: {label}", True)
    elif answer in ("n", "no"):
        ok(f"visual check: {label}", False, "human said it looks wrong")
    else:
        _skip += 1
        print(f"  [SKIP] visual check: {label} (no answer given)")


# ---------------------------------------------------------------------------
# Minimal known-good real images, hand-picked so building test fixtures
# doesn't require an image library (this script stays stdlib-only, matching
# devtools/test.py's own constraint).
# ---------------------------------------------------------------------------
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
    alongside GIF, to prove the JPEG/PNG allowlist isn't just a GIF
    special-case."""
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
    def log_message(self, *_args):
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


args = build_arg_parser(__doc__).parse_args()

step("0. Discovery")
status, help_doc = call("GET", "/help")
ok("GET /help -> 200", status == 200)

setup = setup_project_and_token(args)
if setup is None:
    sys.exit(1)
project_id, TOKEN = setup


# ============================================================================
# 3. GET general_info - schema + data, self-describing
# ============================================================================
step("3. GET general_info")
status, gi = call("GET", f"/{project_id}/general_info", token=TOKEN)
ok("GET general_info -> 200, has fields + data", status == 200 and "fields" in gi and "data" in gi)


# ============================================================================
# 4. Merge semantics + locked-field pinning + combo/type validation
# ============================================================================
step("4a. POST general_info (merge update)")
marker = f"Updated by general_info.test.py at {time.strftime('%Y-%m-%d %H:%M:%S')}"
status, updated = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"remarks": marker})
ok("POST general_info -> 200, remarks updated", status == 200 and updated.get("data", {}).get("remarks") == marker)
status, refetched = call("GET", f"/{project_id}/general_info", token=TOKEN)
ok("GET general_info -> remarks persisted independently of the POST response",
   status == 200 and refetched.get("data", {}).get("remarks") == marker)

step("4b. POST general_info - locked field is pinned, not silently dropped")
status, locked_result = call("POST", f"/{project_id}/general_info", token=TOKEN,
                              body={"project_country": "__should_be_rejected__"})
ok("locked field pinned with a warning", status == 200
   and "warning" in locked_result and "locked_fields_skipped" in locked_result)
status, refetched = call("GET", f"/{project_id}/general_info", token=TOKEN)
ok("GET general_info -> project_country still the original value (not the pin attempt)",
   status == 200 and refetched.get("data", {}).get("project_country") != "__should_be_rejected__")

step("4c. POST general_info - invalid combo value rejected")
status, before_c = call("GET", f"/{project_id}/general_info", token=TOKEN)
original_agency_country = before_c.get("data", {}).get("agency_country")
status, bad_result = call("POST", f"/{project_id}/general_info", token=TOKEN,
                           body={"agency_country": "NotARealCountry"})
ok("invalid value -> 400", status == 400 and bad_result.get("error") == "invalid_field_values",
   detail=f"status={status}")
status, refetched = call("GET", f"/{project_id}/general_info", token=TOKEN)
ok("GET general_info -> agency_country unchanged after rejected write",
   status == 200 and refetched.get("data", {}).get("agency_country") == original_agency_country)

step("4d. POST general_info with an unrecognized key ('abc') is rejected atomically")
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

step("4e. Material shortcuts are 404 not_supported on general_info (str_* only)")
before_shortcuts = get_data(project_id, TOKEN)
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
ok("GET general_info -> data unaffected by any of the misrouted material-shortcut calls above",
   get_data(project_id, TOKEN) == before_shortcuts)


# ============================================================================
# 5. Type validation - wrong JSON type per field is rejected, not coerced
# ============================================================================
step("5. Type validation")
before_types = get_data(project_id, TOKEN)

status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"project_name": 12345})
ok("text field given a number -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"project_name": ["a", "list"]})
ok("text field given a list -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"agency_country": 42})
ok("combo field given a number -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body=["this", "is", "a", "list", "not", "a", "dict"])
ok("POST with a JSON array body (not an object) -> 400 invalid_json_body",
   status == 400 and r.get("error") == "invalid_json_body")

ok("GET general_info -> project_name/agency_country unchanged after every rejected type-mismatched write above",
   get_data(project_id, TOKEN) == before_types)


# ============================================================================
# 6. Injection-style payloads - stored inertly (no execution, no crash)
# ============================================================================
step("6. Injection-style strings are stored inertly")
INJECTION_PAYLOADS = [
    ("sql_like", "'; DROP TABLE projects; --"),
    ("script_tag", "<script>alert(document.cookie)</script>"),
    ("path_traversal", "../../../../etc/passwd"),
    ("null_byte", "before\x00after"),
    ("template_injection", "{{7*7}}${7*7}#{7*7}"),
    ("format_string", "%s%s%s%n"),
    ("very_long", "A" * 20000),
]
for label, payload_str in INJECTION_PAYLOADS:
    status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"remarks": payload_str})
    stored = status == 200 and r.get("data", {}).get("remarks") == payload_str
    ok(f"remarks accepts {label!r}-style string and echoes it back byte-for-byte in the POST response, no crash",
       stored, detail=f"status={status}")
    persisted = get_data(project_id, TOKEN).get("remarks") == payload_str
    ok(f"GET general_info -> {label!r}-style string persisted independently of the POST response, server still up",
       persisted)


# ============================================================================
# 7. upload_img / agency_logo - Pillow-backed JPEG/PNG-only validation
# ============================================================================
step("7a. Schema advertises the JPEG/PNG restriction")
status, gi_schema = call("GET", f"/{project_id}/general_info", token=TOKEN)
logo_field = next((f for f in gi_schema.get("fields", []) if f.get("key") == "agency_logo"), None)
ok("agency_logo field schema lists accepted_image_formats == ['JPEG', 'PNG']",
   status == 200 and logo_field is not None
   and logo_field.get("accepted_image_formats") == ["JPEG", "PNG"])

step("7b. Unreachable image URL is rejected, not silently accepted")
before_7b = get_data(project_id, TOKEN).get("agency_logo")
status, bad_img = call("POST", f"/{project_id}/general_info", token=TOKEN,
                        body={"agency_logo": "https://this-domain-should-not-resolve.invalid/logo.png"})
ok("unreachable image URL -> 400 invalid_field_values", status == 400 and bad_img.get("error") == "invalid_field_values")
ok("GET general_info -> agency_logo unchanged after the rejected write",
   get_data(project_id, TOKEN).get("agency_logo") == before_7b)

step("7c. Real external image URL (live network) is accepted")
status, r = call("POST", f"/{project_id}/general_info", token=TOKEN,
                  body={"agency_logo": "https://placehold.co/600x400/png"})
placehold_logo = r.get("data", {}).get("agency_logo")
ok("https://placehold.co/600x400/png -> 200, real PNG downloaded/converted/stored "
   "(depends on placehold.co being reachable - a network hiccup here isn't a code bug)",
   status == 200 and bool(placehold_logo))
ok("GET general_info -> agency_logo persisted independently of the POST response",
   status == 200 and get_data(project_id, TOKEN).get("agency_logo") == placehold_logo)
if placehold_logo:
    visual_confirm(
        "placehold_co", placehold_logo,
        "a 600x400 grey placeholder image with dark grey diagonal text/graphic on it "
        "(placehold.co's default placeholder look) - NOT blank, NOT garbled/corrupted",
    )

_img_httpd = _start_image_test_server()
_img_port = _img_httpd.server_address[1]
_img_base = f"http://127.0.0.1:{_img_port}"

step("7d. Accepts real PNG/JPEG via URL; rejects real GIF/BMP, non-image content, corrupt data, empty file")
status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"agency_logo": f"{_img_base}/good.png"})
png_url_logo = r.get("data", {}).get("agency_logo")
ok("real PNG via URL -> 200", status == 200 and bool(png_url_logo))
ok("GET general_info -> agency_logo (from good.png) persisted independently of the POST response",
   status == 200 and get_data(project_id, TOKEN).get("agency_logo") == png_url_logo)
if png_url_logo:
    visual_confirm(
        "good_png_via_url", png_url_logo,
        "a plain solid cyan/sky-blue 1x1 pixel image (RGB 0,255,255 - will look like a tiny "
        "cyan square/dot when zoomed) - just confirm it's a valid, non-corrupted, cyan image, "
        "not blank/black/garbled",
    )

status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"agency_logo": f"{_img_base}/good.jpg"})
jpg_url_logo = r.get("data", {}).get("agency_logo")
ok("real JPEG via URL -> 200", status == 200 and bool(jpg_url_logo))
ok("GET general_info -> agency_logo (from good.jpg) persisted independently of the POST response",
   status == 200 and get_data(project_id, TOKEN).get("agency_logo") == jpg_url_logo)
if jpg_url_logo:
    visual_confirm(
        "good_jpg_via_url", jpg_url_logo,
        "a plain solid white 1x1 pixel image (RGB 255,255,255) - just confirm it opens and isn't "
        "blank/black/garbled after Pillow's JPEG re-encode",
    )

before_7d_reject = get_data(project_id, TOKEN).get("agency_logo")
status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"agency_logo": f"{_img_base}/good.gif"})
ok("real, valid GIF via URL -> 400 (format not allowed)", status == 400 and r.get("error") == "invalid_field_values")
ok("GET general_info -> agency_logo unchanged after the rejected GIF write",
   get_data(project_id, TOKEN).get("agency_logo") == before_7d_reject)

status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"agency_logo": f"{_img_base}/good.bmp"})
ok("real, valid BMP via URL -> 400 (confirms a format allowlist, not a GIF special-case)",
   status == 400 and r.get("error") == "invalid_field_values")
ok("GET general_info -> agency_logo unchanged after the rejected BMP write",
   get_data(project_id, TOKEN).get("agency_logo") == before_7d_reject)

status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"agency_logo": f"{_img_base}/not_image.html"})
ok("HTML served in place of an image -> 400", status == 400 and r.get("error") == "invalid_field_values")
ok("GET general_info -> agency_logo unchanged after the rejected HTML write",
   get_data(project_id, TOKEN).get("agency_logo") == before_7d_reject)

status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"agency_logo": f"{_img_base}/corrupt.png"})
ok("corrupt/undecodable PNG bytes -> 400", status == 400 and r.get("error") == "invalid_field_values")
ok("GET general_info -> agency_logo unchanged after the rejected corrupt-PNG write",
   get_data(project_id, TOKEN).get("agency_logo") == before_7d_reject)

status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"agency_logo": f"{_img_base}/empty.png"})
ok("zero-byte file -> 400", status == 400 and r.get("error") == "invalid_field_values")
ok("GET general_info -> agency_logo unchanged after the rejected zero-byte write",
   get_data(project_id, TOKEN).get("agency_logo") == before_7d_reject)

_img_httpd.shutdown()

step("7e. Raw (non-URL) base64 values are Pillow-validated too, not just URL values")
before_7e = get_data(project_id, TOKEN).get("agency_logo")

status, r = call("POST", f"/{project_id}/general_info", token=TOKEN,
                  body={"agency_logo": "this-is-not-base64-image-data-and-not-a-url-either"})
ok("raw non-base64 garbage string -> 400", status == 400 and r.get("error") == "invalid_field_values")
ok("GET general_info -> agency_logo unchanged after the rejected garbage-string write",
   get_data(project_id, TOKEN).get("agency_logo") == before_7e)

status, r = call("POST", f"/{project_id}/general_info", token=TOKEN,
                  body={"agency_logo": base64.b64encode(b"not really an image, just text bytes").decode()})
ok("raw base64-valid-but-not-an-image string -> 400", status == 400 and r.get("error") == "invalid_field_values")
ok("GET general_info -> agency_logo unchanged after the rejected not-an-image write",
   get_data(project_id, TOKEN).get("agency_logo") == before_7e)

status, r = call("POST", f"/{project_id}/general_info", token=TOKEN,
                  body={"agency_logo": base64.b64encode(_GOOD_GIF).decode()})
ok("raw base64 of a real, valid GIF -> 400 (format check applies here too)",
   status == 400 and r.get("error") == "invalid_field_values")
ok("GET general_info -> agency_logo unchanged after the rejected raw-GIF write",
   get_data(project_id, TOKEN).get("agency_logo") == before_7e)

status, r = call("POST", f"/{project_id}/general_info", token=TOKEN,
                  body={"agency_logo": base64.b64encode(_GOOD_BMP).decode()})
ok("raw base64 of a real, valid BMP -> 400", status == 400 and r.get("error") == "invalid_field_values")
ok("GET general_info -> agency_logo unchanged after the rejected raw-BMP write",
   get_data(project_id, TOKEN).get("agency_logo") == before_7e)

step("7f. Empty string clears the field (same as the GUI's Clear button) - run BEFORE the final real-image write")
status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"agency_logo": ""})
ok("empty string -> 200, accepted as a clear", status == 200 and r.get("data", {}).get("agency_logo") == "")
ok("GET general_info -> agency_logo confirmed empty after the clear",
   get_data(project_id, TOKEN).get("agency_logo") == "")

step("7g. Final write: a real PNG, so the run ends with a real, persisted logo (not an empty field)")
final_png_b64 = base64.b64encode(_GOOD_PNG).decode()
status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"agency_logo": final_png_b64})
ok("raw base64 of a real PNG -> 200, accepted and stored as-is",
   status == 200 and r.get("data", {}).get("agency_logo") == final_png_b64)
ok("GET general_info -> agency_logo persisted as the real PNG, byte-for-byte (final state is NOT empty; "
   "raw base64 isn't recompressed, so exact equality is the correct check here, not a visual one)",
   get_data(project_id, TOKEN).get("agency_logo") == final_png_b64)


# ============================================================================
# Summary
# ============================================================================
if _skip:
    print(f"\n{_skip} visual check(s) skipped - decoded images for manual review are in: {_VISUAL_DIR}")
sys.exit(summary())
