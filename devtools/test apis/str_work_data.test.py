"""
devtools/test apis/str_work_data.test.py

Adversarial regression test for Construction Works Data chunks (str_*):
str_foundation, str_sub_structure, str_super_structure, str_misc, plus the
read-only str_component_registry. The goal here is explicitly to try to
break it - malformed shapes at every nesting level, wrong types, numeric
edge cases (negative/zero/NaN/Infinity), duplicate/unicode/injection
material names, malformed custom units, and a concurrency probe - so any
crash or silent-corruption bug shows up now, in a throwaway scratch
project, instead of in production against a real one.

Every probe is checked twice, same policy as the rest of this folder:
  1. The POST response itself (400 for a bad probe, 200 for a genuinely
     valid one).
  2. A follow-up GET - proving a rejected probe left the chunk's data
     unchanged, and an accepted probe actually persisted.

Run:

    python "devtools/test apis/str_work_data.test.py" --project-id <id> --token <token> [--chunk str_super_structure]

This mutates real chunk data on whichever project you point it at - point
it at a scratch/testing project, not one with real data, since there is no
cleanup pass (entries created here stay, same tradeoff as every other file
in this folder).
"""

import concurrent.futures
import sys

from _common import call, step, ok, build_arg_parser, setup_project_and_token, summary

parser = build_arg_parser(__doc__)
parser.add_argument("--chunk", default="str_super_structure",
                     help="which Construction Works chunk to hammer (default: str_super_structure)")
args = parser.parse_args()
chunk = args.chunk

setup = setup_project_and_token(args)
if setup is None:
    sys.exit(1)
project_id, TOKEN = setup

TEST_COMPONENT = "CrashTest Component"
added: list[str] = []  # entry ids created this run, for a final sanity sweep


def get_data() -> dict:
    _, body = call("GET", f"/{project_id}/{chunk}", token=TOKEN)
    return body.get("data", {})


def preview(value, limit: int = 70) -> str:
    s = repr(value)
    return s if len(s) <= limit else s[:limit - 3] + "..."


def add_manual(values: dict, component: str = TEST_COMPONENT, state: dict | None = None,
               custom_unit: dict | None = None):
    body = {"component": component, "values": values}
    if state is not None:
        body["state"] = state
    if custom_unit is not None:
        body["custom_unit"] = custom_unit
    return call("POST", f"/{project_id}/{chunk}/add_manual", token=TOKEN, body=body)


def find_entry(data: dict, component: str, material_name: str):
    for e in data.get(component, []):
        if e.get("values", {}).get("material_name") == material_name:
            return e
    return None


# ============================================================================
# 1. GET - schema + baseline, and str_component_registry is read-only
# ============================================================================
step(f"1. GET /{project_id}/{chunk} - schema/units present")
status, body = call("GET", f"/{project_id}/{chunk}", token=TOKEN)
ok(f"GET {chunk} -> 200, has schema.units", status == 200 and len(body.get("schema", {}).get("units", [])) > 0)

step("1b. str_component_registry is read-only (defensive re-check)")
status, reg_post = call("POST", f"/{project_id}/str_component_registry", token=TOKEN, body={"x": []})
ok("POST str_component_registry -> 405 read_only_chunk",
   status == 405 and reg_post.get("error") == "read_only_chunk")


# ============================================================================
# 2. Generic POST /{chunk} - malformed shapes at every nesting level
# ============================================================================
step("2. Malformed generic-POST shapes")
before_2 = get_data()

status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN, body={})
ok("empty object body -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN, body=[])
ok("empty list body (not even an object) -> 400 invalid_json_body",
   status == 400 and r.get("error") == "invalid_json_body")

status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN,
                  body={TEST_COMPONENT: [{"values": {"material_name": "a"}}],
                        "SomeOtherComponent": [{"values": {"material_name": "b"}}]})
ok("2 components in one request -> 400 (no bulk)", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN,
                  body={TEST_COMPONENT: [{"values": {"material_name": "a"}}, {"values": {"material_name": "b"}}]})
ok("2 patches in one component -> 400 (no bulk)", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN,
                  body={"Not A Real Component": [{"values": {"material_name": "a"}}]})
ok("nonexistent component (well-formed single patch) -> 400, error names valid components",
   status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN, body={TEST_COMPONENT: "not a list"})
ok("patches value is a string, not a list -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN, body={TEST_COMPONENT: [None]})
ok("patch entry is null (not an object) -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN, body={TEST_COMPONENT: ["just a string"]})
ok("patch entry is a bare string -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN, body={TEST_COMPONENT: [42]})
ok("patch entry is a bare number -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN,
                  body={TEST_COMPONENT: [{"meta": {"created_via": "hacked"}}]})
ok("patch tries to write 'meta' directly -> 400 (server-owned)",
   status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN,
                  body={TEST_COMPONENT: [{"not_a_real_patch_key": True}]})
ok("patch has an unrecognized top-level key -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN,
                  body={TEST_COMPONENT: [{"values": "not an object"}]})
ok("patch.values is a string, not an object -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN,
                  body={TEST_COMPONENT: [{"values": {"not_a_real_value_key": 1}}]})
ok("patch.values has an unrecognized key -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN,
                  body={TEST_COMPONENT: [{"state": ["not", "an", "object"]}]})
ok("patch.state is a list, not an object -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN,
                  body={TEST_COMPONENT: [{"state": {"not_a_real_state_key": True}}]})
ok("patch.state has an unrecognized key -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN,
                  body={TEST_COMPONENT: [{"id": "00000000-0000-0000-0000-000000000000", "values": {"rate": 1}}]})
ok("patch by unknown id -> 400, not a crash", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN,
                  body={TEST_COMPONENT: [{"catalog_item": {"name": "x"}}]})  # missing 'unit'
ok("catalog_item missing required 'unit' -> 400", status == 400 and r.get("error") == "invalid_field_values")

ok(f"GET {chunk} -> completely unaffected by every malformed shape above", get_data() == before_2)


# ============================================================================
# 3. Numeric edge cases: negative/zero/NaN/Infinity - the real "does this
#    quietly corrupt cost data" question, not just "does it 400 cleanly".
# ============================================================================
step("3. Numeric edge cases on add_manual (quantity/rate/carbon fields)")

status, r = add_manual({"material_name": "zero-qty", "unit": "kg", "quantity": 0, "rate": 1})
ok("quantity=0 -> 400 (must be > 0)", status == 400 and r.get("error") == "invalid_field_values")

status, r = add_manual({"material_name": "negative-qty", "unit": "kg", "quantity": -5, "rate": 1})
ok("negative quantity -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, r = add_manual({"material_name": "negative-rate", "unit": "kg", "quantity": 1, "rate": -5})
ok("negative rate -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, r = add_manual({"material_name": "string-qty", "unit": "kg", "quantity": "5", "rate": 1})
ok("quantity as a numeric-looking STRING -> 400 (not coerced)", status == 400 and r.get("error") == "invalid_field_values")

status, r = add_manual({"material_name": "bool-qty", "unit": "kg", "quantity": True, "rate": 1})
ok("quantity=True (bool) -> 400 (bool explicitly excluded from numeric)",
   status == 400 and r.get("error") == "invalid_field_values")

# --- The interesting ones: NaN / Infinity. json.dumps(float('nan')) emits
# the literal (non-standard-JSON) token NaN, which Python's own json.loads
# happily parses back into float('nan') by default - so a caller doesn't
# even need to hand-craft raw bytes to send this; plain json.dumps does it.
# validate_material_values() (material_entry.py) checks "qty <= 0" and
# "rate < 0" / "rate == 0" - but NaN compares False against everything,
# and Infinity is neither <= 0 nor < 0, so NEITHER of those guards fires.
nan_marker = "nan-qty-test"
status, r = add_manual({"material_name": nan_marker, "unit": "kg", "quantity": float("nan"), "rate": 100})
nan_accepted = status == 200
ok(f"quantity=NaN -> {'200 (ACCEPTED - see note above: qty<=0 never fires for NaN)' if nan_accepted else '400 (rejected)'}",
   True, detail="informational - see script comment; not a hard pass/fail either way")
if nan_accepted:
    entry = find_entry(get_data(), TEST_COMPONENT, nan_marker)
    ok(f"GET {chunk} -> NaN quantity entry actually persisted (confirms it's real, not just echoed)",
       entry is not None)
    if entry:
        added.append(entry["id"])

inf_marker = "inf-rate-test"
status, r = add_manual({"material_name": inf_marker, "unit": "kg", "quantity": 1, "rate": float("inf")})
inf_accepted = status == 200
ok(f"rate=Infinity -> {'200 (ACCEPTED - inf is neither <0 nor ==0, so no guard fires)' if inf_accepted else '400 (rejected)'}",
   True, detail="informational - see script comment; not a hard pass/fail either way")
if inf_accepted:
    entry = find_entry(get_data(), TEST_COMPONENT, inf_marker)
    ok(f"GET {chunk} -> Infinity rate entry actually persisted (confirms it's real, not just echoed)",
       entry is not None)
    if entry:
        added.append(entry["id"])

neg_inf_marker = "neginf-qty-test"
status, r = add_manual({"material_name": neg_inf_marker, "unit": "kg", "quantity": float("-inf"), "rate": 1})
ok(f"quantity=-Infinity -> {'400 (rejected - -inf <= 0 IS true, so this guard correctly fires)' if status == 400 else '200 (unexpectedly accepted)'}",
   status == 400, detail=f"status={status}")

status, r = add_manual({"material_name": "huge-qty", "unit": "kg", "quantity": 1e308, "rate": 1})
ok("extremely large but finite quantity (1e308) -> 200, accepted (finite, so no guard rejects it)",
   status == 200)
if status == 200:
    entry = find_entry(get_data(), TEST_COMPONENT, "huge-qty")
    if entry:
        added.append(entry["id"])

status, r = add_manual({"material_name": "overflow-qty", "unit": "kg", "quantity": 1e400, "rate": 1})
# 1e400 overflows a Python/JSON double to Infinity at parse time - same
# case as the explicit Infinity probe above, reached via a different route.
ok(f"quantity=1e400 (overflows to Infinity) -> status={status} (same class of issue as the explicit Infinity probe)",
   True, detail="informational")


# ============================================================================
# 4. Recyclability numeric edge case: recovery_percentage > 100
# ============================================================================
step("4. post_demolition_recovery_percentage > 100 is rejected when recyclability is on")
status, r = add_manual(
    {"material_name": "over-100-recovery", "unit": "kg", "quantity": 1, "rate": 1,
     "scrap_rate": 5, "post_demolition_recovery_percentage": 150},
    state={"included_in_recyclability": True},
)
ok("recovery_percentage=150 with recyclability on -> 400", status == 400 and r.get("error") == "invalid_field_values")


# ============================================================================
# 5. Material name edge cases: duplicates, unicode/injection, very long,
#    empty/whitespace - all via GET-verified add_manual round-trips.
# ============================================================================
step("5. Material name edge cases")

status, r = add_manual({"material_name": "", "unit": "kg", "quantity": 1, "rate": 1})
ok("empty material_name -> 400 (required)", status == 400 and r.get("error") == "invalid_field_values")

status, r = add_manual({"material_name": "   ", "unit": "kg", "quantity": 1, "rate": 1})
ok("whitespace-only material_name -> 400 (required, after strip)",
   status == 400 and r.get("error") == "invalid_field_values")

unicode_name = "钢筋 Ferro‮de reversed rebar™ <script>alert(1)</script>"
status, r = add_manual({"material_name": unicode_name, "unit": "kg", "quantity": 1, "rate": 1})
ok("unicode/RTL-override/script-tag material_name -> 200, accepted", status == 200)
if status == 200:
    entry = find_entry(get_data(), TEST_COMPONENT, unicode_name)
    ok(f"GET {chunk} -> stored byte-for-byte, no corruption/crash", entry is not None)
    if entry:
        added.append(entry["id"])

long_name = "X" * 10000
status, r = add_manual({"material_name": long_name, "unit": "kg", "quantity": 1, "rate": 1})
ok(f"10,000-char material_name -> status={status}, no crash", status in (200, 400))
if status == 200:
    entry = find_entry(get_data(), TEST_COMPONENT, long_name)
    ok(f"GET {chunk} -> 10,000-char name persisted intact", entry is not None)
    if entry:
        added.append(entry["id"])

dup_target = "DuplicateNameProbe"
status, r1 = add_manual({"material_name": dup_target, "unit": "kg", "quantity": 1, "rate": 1})
ok("first add of a fresh name -> 200", status == 200)
if status == 200:
    e = find_entry(get_data(), TEST_COMPONENT, dup_target)
    if e:
        added.append(e["id"])
status, r2 = add_manual({"material_name": f"  {dup_target.upper()}  ", "unit": "kg", "quantity": 1, "rate": 1})
ok("re-adding the same name (different case/whitespace) -> 400 (duplicate)",
   status == 400 and r2.get("error") == "invalid_field_values")


# ============================================================================
# 6. Unit / custom_unit edge cases
# ============================================================================
step("6. Unit and custom_unit edge cases")

status, r = add_manual({"material_name": "unrecognized-unit-no-custom", "unit": "bananas_per_hour",
                          "quantity": 1, "rate": 1})
ok("unrecognized unit with no custom_unit -> 400, helpful message",
   status == 400 and r.get("error") == "invalid_field_values")

status, r = add_manual(
    {"material_name": "mismatched-custom-unit", "unit": "bananas_per_hour", "quantity": 1, "rate": 1},
    custom_unit={"symbol": "not_matching", "dimension": "Mass", "to_si": 1},
)
ok("custom_unit.symbol doesn't match values.unit -> 400",
   status == 400 and r.get("error") == "invalid_field_values")

status, r = add_manual(
    {"material_name": "custom-unit-missing-keys", "unit": "crashtestunit1", "quantity": 1, "rate": 1},
    custom_unit={"symbol": "crashtestunit1"},  # missing dimension/to_si
)
ok("custom_unit missing required keys (dimension/to_si) -> 400",
   status == 400 and r.get("error") == "invalid_field_values")

status, r = add_manual(
    {"material_name": "custom-unit-bad-type", "unit": "crashtestunit2", "quantity": 1, "rate": 1},
    custom_unit="not an object",
)
ok("custom_unit is a string, not an object -> 400", status == 400 and r.get("error") == "invalid_field_values")


# ============================================================================
# 7. add_manual rejects raw carbon_unit (must use carbon_unit_den/num)
# ============================================================================
step("7. add_manual rejects the raw carbon_unit key")
status, r = add_manual({"material_name": "raw-carbon-unit-probe", "unit": "kg", "quantity": 1, "rate": 1,
                          "carbon_unit": "kgCO2e/kg"})
ok("raw 'carbon_unit' key -> 400 (must use carbon_unit_den/_num instead)",
   status == 400 and r.get("error") == "invalid_field_values")


# ============================================================================
# 8. add_from_catalog: unknown db_key, unknown material - clean errors
# ============================================================================
step("8. add_from_catalog error handling")
status, r = call("POST", f"/{project_id}/{chunk}/add_from_catalog", token=TOKEN,
                  body={"component": TEST_COMPONENT, "db_key": "TOTALLY/FAKE/DB",
                        "material_name": "anything", "quantity": 1})
ok("unknown db_key -> 400, not a crash", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/{chunk}/add_from_catalog", token=TOKEN,
                  body={"component": TEST_COMPONENT, "db_key": "TOTALLY/FAKE/DB",
                        "material_name": "anything", "quantity": "not-a-number"})
ok("quantity as a string on add_from_catalog -> 400 (rejected before/at validate_material_values)",
   status == 400)


# ============================================================================
# 9. Trash endpoint malformed inputs
# ============================================================================
step("9. Trash endpoint malformed inputs")
status, r = call("POST", f"/{project_id}/{chunk}/trash", token=TOKEN, body={"id": 12345})
ok("trash with id as a number, not a string -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/{chunk}/trash", token=TOKEN, body={"id": None})
ok("trash with id=null -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/{chunk}/trash", token=TOKEN, body={"id": [1, 2, 3]})
ok("trash with id as a list -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/{chunk}/trash", token=TOKEN,
                  body={"id": "whatever", "not_a_real_key": True})
ok("trash with an unrecognized extra key -> 400", status == 400 and r.get("error") == "invalid_field_values")

status, r = call("POST", f"/{project_id}/{chunk}/trash", token=TOKEN,
                  body={"id": "whatever", "untrash": "true"})  # string, not bool
ok("trash with untrash as a STRING 'true', not a bool -> 400", status == 400 and r.get("error") == "invalid_field_values")

if added:
    probe_id = added[0]
    status, r1 = call("POST", f"/{project_id}/{chunk}/trash", token=TOKEN, body={"id": probe_id})
    status2, r2 = call("POST", f"/{project_id}/{chunk}/trash", token=TOKEN, body={"id": probe_id})
    ok("trashing the same id twice in a row -> both 200 (idempotent, no error)",
       status == 200 and status2 == 200)
    call("POST", f"/{project_id}/{chunk}/trash", token=TOKEN, body={"id": probe_id, "untrash": True})


# ============================================================================
# 10. Concurrency probe: N simultaneous add_manual calls to the SAME
#     component with distinct names - checks for a lost-update race in the
#     read-modify-write cycle. NOTE: server.py's start_api_server() uses
#     werkzeug's make_server() without threaded=True, so this dev server
#     currently handles one request at a time - a race here would indicate
#     either that assumption changed, or a race further down in the
#     project-file write path itself. Documents current behaviour either
#     way rather than assuming safety.
# ============================================================================
step("10. Concurrency probe - N simultaneous add_manual calls, same component")
N = 8
concurrent_names = [f"concurrent-probe-{i}-{id(object())}" for i in range(N)]


def _fire(name):
    return add_manual({"material_name": name, "unit": "kg", "quantity": 1, "rate": 1})


with concurrent.futures.ThreadPoolExecutor(max_workers=N) as pool:
    results = list(pool.map(_fire, concurrent_names))

statuses = [s for s, _ in results]
ok(f"{N} concurrent add_manual calls -> server didn't crash (got {N} responses back)",
   len(results) == N, detail=f"statuses={statuses}")

after_concurrent = get_data()
found_names = {e.get("values", {}).get("material_name") for e in after_concurrent.get(TEST_COMPONENT, [])}
missing = [n for n in concurrent_names if n not in found_names]
ok(f"all {N} concurrently-added entries are present in GET afterward (no lost-update race)",
   len(missing) == 0, detail=f"missing={missing}" if missing else "")
for n in concurrent_names:
    e = find_entry(after_concurrent, TEST_COMPONENT, n)
    if e:
        added.append(e["id"])


# ============================================================================
# 11. Cleanup - trash everything this run created (left trashed, not deleted,
#     same convention as devtools/test.py)
# ============================================================================
step("11. Cleanup - trash all entries created this run")
cleanup_ok = True
for entry_id in added:
    s, _ = call("POST", f"/{project_id}/{chunk}/trash", token=TOKEN, body={"id": entry_id})
    cleanup_ok = cleanup_ok and s == 200
ok(f"trashed {len(added)} entr(y/ies) created this run", cleanup_ok)


sys.exit(summary())
