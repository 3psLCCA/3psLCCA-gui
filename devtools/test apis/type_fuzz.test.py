"""
devtools/test apis/type_fuzz.test.py

Exhaustive per-field type-fuzzing for any FieldDef-schema chunk (default:
general_info). For every writable (non-locked) field, sends every JSON type
that field's declared field_type should reject, and confirms two things per
probe:
  1. The POST response itself (400 invalid_field_values for a bad probe,
     200 for a probe that's genuinely valid).
  2. A follow-up GET - proving a rejected probe left the stored value
     untouched, and an accepted probe actually persisted, not just got
     echoed back in that one response.

Expectations are grounded in the REAL server code (see
gui/api/registry.py's validate_payload_keys), not assumptions about what
"should" happen:
  - text / textarea / phone / upload_img -> must be a string. That's ALL
    that's checked: "phone" has NO digit/format/regex validation - a date
    string or arbitrary prose is a perfectly valid string and WILL be
    accepted. This script surfaces that plainly (as an "accepts" check,
    not a bug) rather than assuming phone numbers are validated as such.
  - combo -> must be a string AND must exactly match one of the field's
    declared options.
  - int / float -> must be an int/float and NOT a bool (Python's
    isinstance(True, int) is True, so the server explicitly excludes
    bools - see registry.py:241); also checked against min/max if the
    schema declares a range.

Run:

    python "devtools/test apis/type_fuzz.test.py" --project-id <id> --token <token> [--chunk general_info]

This mutates real chunk data on whichever project you point it at (same as
fill_empty_fields.test.py) - point it at a scratch/testing project, not a
project with real data you care about, since there is no cleanup pass.
"""

import sys

from _common import call, step, ok, build_arg_parser, setup_project_and_token, summary

parser = build_arg_parser(__doc__)
parser.add_argument("--chunk", default="general_info",
                     help="which FieldDef-schema chunk to fuzz (default: general_info)")
args = parser.parse_args()
chunk = args.chunk

setup = setup_project_and_token(args)
if setup is None:
    sys.exit(1)
project_id, TOKEN = setup


def get_data() -> dict:
    _, body = call("GET", f"/{project_id}/{chunk}", token=TOKEN)
    return body.get("data", {})


def preview(value, limit: int = 60) -> str:
    s = repr(value)
    return s if len(s) <= limit else s[:limit - 3] + "..."


# ============================================================================
# 1. GET - understand the real schema before fuzzing anything
# ============================================================================
step(f"1. GET /{project_id}/{chunk} - understand schema before fuzzing")
status, gi = call("GET", f"/{project_id}/{chunk}", token=TOKEN)
ok(f"GET {chunk} -> 200, self-describing (has 'fields')", status == 200 and "fields" in gi)
if status != 200 or "fields" not in gi:
    print(f"  '{chunk}' has no flat field schema (table/nested chunk?) - nothing to fuzz here. "
          f"This tool only works on Tier A/B pages (general_info, bridge_data, financial_data, "
          f"demolition_data, maintenance_data).")
    sys.exit(summary())

field_defs = [f for f in gi["fields"] if f.get("type") == "field"]
print(f"  {len(field_defs)} field(s) in schema: "
      + ", ".join(f"{f['key']}({f.get('field_type')})" for f in field_defs))


# ============================================================================
# 2. Probe batteries
# ============================================================================
# Every JSON type a field COULD receive from a careless/adversarial caller -
# used against every field type; expected_reject() decides per-field which
# of these should 400.
TYPE_PROBES = [
    ("null", None),
    ("bool_true", True),
    ("bool_false", False),
    ("int", 424242),
    ("float", 3.14159),
    ("list", ["a", "list", "of", "strings"]),
    ("dict", {"nested": "object"}),
]

# Valid JSON type, wrong SEMANTIC shape - expected to be ACCEPTED under the
# current contract (type-only validation, no format/regex check). Reported
# as a real accept/persist assertion, not just an FYI print.
SHAPE_PROBES = {
    "phone": [
        ("date_string", "2024-01-01"),
        ("plain_prose", "this is not a phone number at all"),
        ("digits_as_string", "1234567890"),
    ],
    "text": [("date_string", "2024-01-01")],
    "textarea": [("date_string", "2024-01-01")],
}


def expected_reject(field_type: str, probe_value) -> bool:
    """Mirrors gui/api/registry.py's validate_payload_keys exactly, so
    this fuzzer's expectations are grounded in the real server code."""
    if field_type in ("text", "textarea", "phone", "upload_img"):
        return not isinstance(probe_value, str)
    if field_type == "combo":
        return not isinstance(probe_value, str)  # option-membership is checked separately below
    if field_type in ("int", "float"):
        if isinstance(probe_value, bool):
            return True
        return not isinstance(probe_value, (int, float))
    return False  # unknown field_type - no expectation either way


# ============================================================================
# 3. Fuzz every writable field
# ============================================================================
step("2. Type-fuzz every writable field")
for fd in field_defs:
    key = fd["key"]
    ftype = fd.get("field_type")

    if fd.get("locked"):
        print(f"\n  -- {key!r} ({ftype}) - skipped, locked field --")
        continue

    print(f"\n  -- {key!r} ({ftype}) --")
    before = get_data().get(key)

    for label, probe in TYPE_PROBES:
        should_reject = expected_reject(ftype, probe)
        status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN, body={key: probe})

        if should_reject:
            ok(f"{key!r} ({ftype}) rejects {label} ({preview(probe)}) -> 400",
               status == 400 and r.get("error") == "invalid_field_values", detail=f"status={status}")
            ok(f"GET {chunk} -> {key!r} unchanged after rejected {label} probe",
               get_data().get(key) == before)
        else:
            ok(f"{key!r} ({ftype}) accepts {label} ({preview(probe)}) -> 200",
               status == 200, detail=f"status={status}, body={preview(r)}")
            after = get_data().get(key)
            ok(f"GET {chunk} -> {key!r} persisted {label} independently of the POST response",
               after == probe)
            if status == 200:
                before = after

    if ftype == "combo":
        options = fd.get("options") or []
        bogus = "Definitely Not A Real Option 12345"
        assert bogus not in options
        status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN, body={key: bogus})
        ok(f"{key!r} (combo) rejects a well-formed string that isn't a real option -> 400",
           status == 400 and r.get("error") == "invalid_field_values", detail=f"status={status}")
        ok(f"GET {chunk} -> {key!r} unchanged after the not-a-real-option probe",
           get_data().get(key) == before)

    if ftype in ("int", "float") and (fd.get("min") is not None or fd.get("max") is not None):
        lo, hi = fd.get("min"), fd.get("max")
        out_of_range = (hi + 1) if hi is not None else (lo - 1 if lo is not None else None)
        if out_of_range is not None:
            status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN, body={key: out_of_range})
            ok(f"{key!r} ({ftype}) rejects an out-of-range in-type value ({out_of_range}) -> 400",
               status == 400 and r.get("error") == "invalid_field_values", detail=f"status={status}")
            ok(f"GET {chunk} -> {key!r} unchanged after the out-of-range probe",
               get_data().get(key) == before)

    for label, probe in SHAPE_PROBES.get(ftype, []):
        status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN, body={key: probe})
        accepted = status == 200 and r.get("data", {}).get(key) == probe
        ok(f"{key!r} ({ftype}) accepts {label} ({preview(probe)}) -> 200 "
           f"(type-only validation - no format/regex check exists for this field_type)",
           accepted, detail=f"status={status}")
        if accepted:
            ok(f"GET {chunk} -> {key!r} persisted {label} independently of the POST response",
               get_data().get(key) == probe)
            before = probe


sys.exit(summary())
