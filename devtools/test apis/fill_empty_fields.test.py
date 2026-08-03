"""
devtools/test apis/fill_empty_fields.test.py

Utility/regression check for any FieldDef-schema chunk (Tier A/B pages -
general_info, bridge_data, financial_data, demolition_data,
maintenance_data): inventories every field via GET, lists which ones are
currently empty, builds a sensible fill value per field's declared
type/options for exactly those empty + writable (non-locked) fields, POSTs
that payload, then GETs again to confirm each value actually landed - not
just that the POST returned 200.

Run:

    python "devtools/test apis/fill_empty_fields.test.py" --project-id <id> --token <token> [--chunk general_info]

--project-id/--token/interactive picker behave exactly like the other
files in this folder - see _common.py. --chunk defaults to general_info.

Skips (does not try to fill):
  - locked fields (schema "locked": true - e.g. project_country, currency,
    unit_system - the API keeps these fixed at creation, POSTing them is a
    silent no-op with a warning, not a real write)
  - combo fields with no real (non-placeholder) options to choose from
    (e.g. a fresh project's sor_database, which is [] until a database is
    configured - POSTing an empty-options combo 400s)
  - upload_img fields are filled with a real, valid, tiny PNG (JPEG/PNG is
    the only accepted format - see image_upload.py) so the fill actually
    succeeds rather than being rejected by the format allowlist
"""

import base64
import sys

from _common import call, step, ok, build_arg_parser, setup_project_and_token, summary

# A real, valid, minimal PNG (1x1, solid cyan) - reused as a generic
# "fill an upload_img field with something that will actually pass
# validation" value, regardless of which chunk/field it targets.
_FILL_PNG_B64 = base64.b64encode(base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+P+/HgAFhAJ/wlseKgAAAABJRU5ErkJggg=="
)).decode()


def sample_value(fd: dict):
    """Picks a plausible, schema-valid value for one field description
    (as returned in GET .../<chunk>'s "fields" list) - or None if this
    field type/state can't be safely filled (caller should skip it)."""
    ftype = fd.get("field_type")
    key = fd.get("key", "")

    if ftype == "combo":
        options = [o for o in (fd.get("options") or []) if o and "select" not in o.lower()]
        return options[0] if options else None
    if ftype == "text":
        return f"Filled by fill_empty_fields.test.py ({key})"
    if ftype == "textarea":
        return f"Filled by fill_empty_fields.test.py for '{key}' - a longer free-text sample value."
    if ftype == "phone":
        return "+1-555-0100"
    if ftype == "int":
        lo = fd.get("min")
        return int(lo) if lo is not None else 1
    if ftype == "float":
        lo = fd.get("min")
        return float(lo) if lo is not None else 1.0
    if ftype == "upload_img":
        return _FILL_PNG_B64
    return None


def is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and (value.strip() == "" or "select" in value.lower()):
        return True
    return False


parser = build_arg_parser(__doc__)
parser.add_argument("--chunk", default="general_info",
                     help="which FieldDef-schema chunk to fill (default: general_info)")
args = parser.parse_args()
chunk = args.chunk

setup = setup_project_and_token(args)
if setup is None:
    sys.exit(1)
project_id, TOKEN = setup


# ============================================================================
# 1. GET - inventory every field and its current value
# ============================================================================
step(f"1. GET /{project_id}/{chunk} - inventory current fields")
status, gi = call("GET", f"/{project_id}/{chunk}", token=TOKEN)
ok(f"GET {chunk} -> 200, self-describing (has 'fields')", status == 200 and "fields" in gi)
if status != 200 or "fields" not in gi:
    print(f"  '{chunk}' isn't a FieldDef-schema chunk (or isn't reachable) - nothing to fill. "
          f"This tool only works on Tier A/B pages (general_info, bridge_data, financial_data, "
          f"demolition_data, maintenance_data) - table/nested chunks (str_*) have no flat field list.")
    sys.exit(summary())

field_defs = [f for f in gi["fields"] if f.get("type") == "field"]
data = gi.get("data", {})


# ============================================================================
# 2. List every field's state: empty/writable, empty/locked, or has a value
# ============================================================================
def _preview(value, limit: int = 60) -> str:
    """Truncates long values (e.g. base64 image data, or a 20000-char
    injection-test leftover) so the field inventory stays readable instead
    of dumping the raw value straight into the terminal."""
    s = repr(value)
    return s if len(s) <= limit else s[:limit - 3] + "..."


step("2. Field inventory")
empty_writable: list[dict] = []
empty_locked: list[str] = []
already_filled: list[str] = []

for fd in field_defs:
    key = fd["key"]
    value = data.get(key)
    if is_empty(value):
        if fd.get("locked"):
            empty_locked.append(key)
            print(f"  [EMPTY, LOCKED - skipped]   {key!r} = {_preview(value)}")
        else:
            empty_writable.append(fd)
            print(f"  [EMPTY, writable]           {key!r} = {_preview(value)}")
    else:
        already_filled.append(key)
        print(f"  [has a value]                {key!r} = {_preview(value)}")

ok(f"inventoried {len(field_defs)} field(s): {len(empty_writable)} empty+writable, "
   f"{len(empty_locked)} empty+locked (skipped), {len(already_filled)} already filled", True)


# ============================================================================
# 3. Build a fill payload for the empty+writable fields and POST it
# ============================================================================
step("3. Build fill payload and POST")
payload = {}
skipped_no_sample: list[str] = []
for fd in empty_writable:
    value = sample_value(fd)
    if value is None:
        skipped_no_sample.append(fd["key"])
        continue
    payload[fd["key"]] = value

if skipped_no_sample:
    print(f"  no safe sample value for: {skipped_no_sample} (e.g. a combo with no real options) - left empty")

print(f"  payload ({len(payload)} field(s)): "
      f"{ {k: (v if len(str(v)) < 60 else v[:57] + '...') for k, v in payload.items()} }")

if not payload:
    print("  nothing to fill - every field already has a value, or none had a safe sample value.")
else:
    status, posted = call("POST", f"/{project_id}/{chunk}", token=TOKEN, body=payload)
    ok(f"POST {chunk} -> 200", status == 200, detail=f"status={status}, body={posted}")


    # ========================================================================
    # 4. GET again - confirm each field actually persisted, not just echoed
    # ========================================================================
    step("4. GET again - confirm values were actually added")
    status, refetched = call("GET", f"/{project_id}/{chunk}", token=TOKEN)
    ok(f"GET {chunk} -> 200", status == 200)
    new_data = refetched.get("data", {})
    for key, expected in payload.items():
        actual = new_data.get(key)
        ok(f"{key!r} persisted correctly (was empty -> now {expected!r})", actual == expected,
           detail=f"got {actual!r}")


sys.exit(summary())
