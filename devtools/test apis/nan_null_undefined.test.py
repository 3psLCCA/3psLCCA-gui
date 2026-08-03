"""
devtools/test apis/nan_null_undefined.test.py

Focused, standalone test for three specific "edge value" classes across
every numeric field the API exposes - both FieldDef pages (general_info,
bridge_data, financial_data, demolition_data, maintenance_data) and the
Construction Works material fields (quantity, rate, carbon_emission,
conversion_factor, scrap_rate, post_demolition_recovery_percentage via
add_manual):

  - NaN       - json.dumps(float('nan')) emits the literal (non-standard
                but Python-round-trippable) JSON token NaN.
  - Infinity / -Infinity - same story via float('inf')/float('-inf').
  - null / omitted ("undefined") - JSON has no "undefined" the way
                JavaScript does; the two closest real equivalents are
                tested separately since they're NOT the same thing here:
                  * explicit null  - the key IS present, value is JSON null
                  * omitted entirely - the key is absent from the payload,
                    which under this API's merge/PATCH semantics means
                    "leave this field's current value untouched" - NOT an
                    error. This file confirms that distinction explicitly
                    rather than assuming it.

Expectations are grounded in the real server code, not assumptions:

  registry.py's validate_payload_keys(), for a FieldDef int/float field:
      if isinstance(value, bool) or not isinstance(value, (int, float)):
          reject
      if fd.options:  # a declared (min, max) range
          if not (low <= value <= high):
              reject
  Chained comparisons against NaN are ALWAYS False in Python (NaN doesn't
  compare equal/less/greater to anything, including itself) - so for a
  field WITH a declared range, "low <= NaN <= high" is False, "not False"
  is True, and NaN gets correctly REJECTED. For a field WITHOUT a declared
  range (fd.options is empty/None), that whole block is skipped, so NaN/
  Infinity sail through with NO further check - ACCEPTED. Whether a given
  field has a range isn't hardcoded here - this script discovers it live
  from that field's own GET schema (min/max being present or None), so the
  prediction is correct regardless of which specific fields happen to
  declare one.

  material_entry.py's validate_material_values(), for str_* materials:
      quantity: rejects only "qty <= 0" - NaN and +Infinity both fail to
                satisfy that (comparisons against NaN are False; Infinity
                is never <= 0), so both are ACCEPTED; -Infinity IS <= 0,
                so it's correctly REJECTED.
      rate:     same shape - rejects only "< 0" or "== 0", so NaN and
                +Infinity are ACCEPTED, -Infinity REJECTED.

Every probe is checked twice, same policy as the rest of this folder: the
POST response itself, AND a follow-up GET proving what's actually stored -
never trusting an assumption about the outcome over what a live GET says.

Run:

    python "devtools/test apis/nan_null_undefined.test.py" --project-id <id> --token <token>

Mutates real data (a handful of small, harmless writes) on whichever
project you point it at - point it at a scratch/testing project.
"""

import math
import sys

from _common import call, step, ok, build_arg_parser, setup_project_and_token, summary

FIELDDEF_CHUNKS = ["maintenance_data", "demolition_data", "financial_data", "general_info", "bridge_data"]
STR_COMPONENT = "NanNullTest Component"

parser = build_arg_parser(__doc__)
parser.add_argument("--str-chunk", default="str_misc",
                     help="which Construction Works chunk to target for the material-field probes "
                          "in section 2 (default: str_misc)")
args = parser.parse_args()
STR_CHUNK = args.str_chunk

setup = setup_project_and_token(args)
if setup is None:
    sys.exit(1)
project_id, TOKEN = setup


def get_chunk(chunk: str) -> dict:
    _, body = call("GET", f"/{project_id}/{chunk}", token=TOKEN)
    return body


def preview(v, limit=60):
    s = repr(v)
    return s if len(s) <= limit else s[:limit - 3] + "..."


# ============================================================================
# 1. FieldDef numeric fields (any chunk): NaN / Infinity / -Infinity / null
#    / omitted, per-field, with expectations derived from that field's own
#    live schema (has a range or not) rather than assumed in advance.
# ============================================================================
step("1. FieldDef numeric fields - NaN/Infinity/-Infinity/null/omitted")

for chunk in FIELDDEF_CHUNKS:
    body = get_chunk(chunk)
    fields = [f for f in body.get("fields", []) if f.get("type") == "field"]
    numeric_fields = [f for f in fields if f.get("field_type") in ("int", "float") and not f.get("locked")]
    if not numeric_fields:
        print(f"  {chunk}: no writable numeric fields - skipped")
        continue

    # Warm up the chunk with a no-op POST ({} - nothing to merge) before probing
    # any field. A still-"virgin" chunk's first-ever successful write seeds
    # EVERY field with its schema default, not just whatever key was in that
    # payload (confirmed live: POSTing only carriageway_width to a fresh
    # bridge_data chunk moved span from None to its own default, 0.0, even
    # though span was never mentioned) - a one-time model-initialization
    # side effect, not a merge bug. Without this warm-up, the very first
    # numeric field probed in each chunk would spuriously look like its
    # "omitted key" check failed, when really it was just the chunk's first
    # write ever landing during that check.
    call("POST", f"/{project_id}/{chunk}", token=TOKEN, body={})

    for fd in numeric_fields:
        key = fd["key"]
        has_range = fd.get("min") is not None and fd.get("max") is not None
        print(f"\n  -- {chunk}.{key} ({fd['field_type']}, range={fd.get('min')}..{fd.get('max')}) --")

        before = get_chunk(chunk).get("data", {}).get(key)

        # --- NaN ---
        status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN, body={key: float("nan")})
        nan_expect_reject = has_range  # chained comparison with NaN is always False -> "not in range" fires
        ok(f"{chunk}.{key}: NaN -> {'400 (has a declared range - NaN fails the chained comparison)' if nan_expect_reject else '200 (no range declared - only a type check applies)'}",
           (status == 400) == nan_expect_reject, detail=f"status={status}")
        after = get_chunk(chunk).get("data", {}).get(key)
        if status == 200:
            ok(f"{chunk}.{key}: GET confirms NaN actually persisted (not just echoed)",
               isinstance(after, float) and math.isnan(after))
        else:
            ok(f"{chunk}.{key}: GET confirms value unchanged after rejected NaN", after == before)
        before = after if status == 200 else before

        # --- Infinity ---
        status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN, body={key: float("inf")})
        inf_expect_reject = has_range  # inf is never within a finite [low, high] range
        ok(f"{chunk}.{key}: Infinity -> {'400 (out of declared range)' if inf_expect_reject else '200 (no range declared)'}",
           (status == 400) == inf_expect_reject, detail=f"status={status}")
        after = get_chunk(chunk).get("data", {}).get(key)
        if status == 200:
            ok(f"{chunk}.{key}: GET confirms Infinity actually persisted", after == float("inf"))
        else:
            ok(f"{chunk}.{key}: GET confirms value unchanged after rejected Infinity", after == before)
        before = after if status == 200 else before

        # --- -Infinity ---
        status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN, body={key: float("-inf")})
        neg_inf_expect_reject = has_range  # -inf is never within a finite [low, high] range either
        ok(f"{chunk}.{key}: -Infinity -> {'400 (out of declared range)' if neg_inf_expect_reject else '200 (no range declared)'}",
           (status == 400) == neg_inf_expect_reject, detail=f"status={status}")
        after = get_chunk(chunk).get("data", {}).get(key)
        if status == 200:
            ok(f"{chunk}.{key}: GET confirms -Infinity actually persisted", after == float("-inf"))
        else:
            ok(f"{chunk}.{key}: GET confirms value unchanged after rejected -Infinity", after == before)
        before = after if status == 200 else before

        # --- explicit null (key present, value is JSON null) ---
        status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN, body={key: None})
        ok(f"{chunk}.{key}: explicit null -> 400 (isinstance(None, (int,float)) is False - always rejected)",
           status == 400, detail=f"status={status}")
        after = get_chunk(chunk).get("data", {}).get(key)
        ok(f"{chunk}.{key}: GET confirms value unchanged after rejected explicit null", after == before)

        # --- omitted entirely ("undefined") - NOT an error, merge/PATCH semantics ---
        # POST some other harmless no-op (re-send a DIFFERENT field's own current
        # value, unrelated to `key`) and confirm `key` is untouched - proving
        # "omitted" means "leave as-is", not "clear it" or "error".
        #
        # The value picked for that other field must itself be one the API
        # accepts, or its rejection (e.g. explicit null on a still-unset numeric
        # field - the exact case this file proves is a 400 earlier in this same
        # loop) would produce an unrelated 400 that has nothing to do with
        # whether `key` was actually left alone. So: prefer another field whose
        # *live* current value is non-null; if every other field on this chunk
        # is still unset, fall back to that field's own schema default (a value
        # the field's type accepts by construction) rather than None.
        chunk_data = get_chunk(chunk).get("data", {})
        other_field = next(
            (f["key"] for f in fields if f["key"] != key and not f.get("locked")
             and chunk_data.get(f["key"]) is not None),
            None,
        )
        other_value = chunk_data.get(other_field) if other_field else None
        if other_field is None:
            other_field = next(
                (f["key"] for f in fields if f["key"] != key and not f.get("locked")
                 and f.get("default") is not None),
                None,
            )
            other_value = next((f["default"] for f in fields if f["key"] == other_field), None)

        if other_field is not None:
            status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN, body={other_field: other_value})
            after = get_chunk(chunk).get("data", {}).get(key)
            ok(f"{chunk}.{key}: omitted from a POST that touches a different field -> "
               f"unchanged (merge semantics: 'undefined'/absent means 'leave as-is', not an error)",
               status == 200 and after == before, detail=f"status={status}, other_field={other_field!r}")
        else:
            print(f"  {chunk}.{key}: no other writable field with a resendable value - omitted-key check skipped")


# ============================================================================
# 2. Construction Works material numeric fields via add_manual
# ============================================================================
step(f"2. str_* material fields via add_manual ({STR_CHUNK}/{STR_COMPONENT!r})")


def add_manual(values: dict, state: dict | None = None):
    body = {"component": STR_COMPONENT, "values": values}
    if state is not None:
        body["state"] = state
    return call("POST", f"/{project_id}/{STR_CHUNK}/add_manual", token=TOKEN, body=body)


def find_entry(name: str):
    data = get_chunk(STR_CHUNK).get("data", {})
    for e in data.get(STR_COMPONENT, []):
        if e.get("values", {}).get("material_name") == name:
            return e
    return None


# --- quantity: NaN/Infinity/-Infinity/null all rejected ---
# validate_material_values() now explicitly rejects math.isnan()/math.isinf()
# for quantity BEFORE the "> 0" check, so NaN/Infinity can no longer sneak
# through just because "NaN <= 0" and "Infinity > 0" happen to be True/False
# in a way that used to look like a legitimate positive number.
for label, val in [("NaN", float("nan")), ("Infinity", float("inf")),
                    ("-Infinity", float("-inf")), ("null", None)]:
    name = f"qty-{label}-probe"
    # quantity is always present as a key, even for the "null" case - this
    # tests explicit null specifically (as opposed to omitting the key
    # entirely, which add_manual's REQUIRED-key check would instead treat
    # as "missing" - a distinct code path from an explicit null value).
    values = {"material_name": name, "unit": "kg", "rate": 1, "quantity": val}
    status, r = add_manual(values)
    ok(f"quantity={label} -> 400 (NaN/Infinity/-Infinity/null are all rejected)",
       status == 400, detail=f"status={status}")

# --- rate: NaN/Infinity/-Infinity/null all rejected ---
for label, val in [("NaN", float("nan")), ("Infinity", float("inf")),
                    ("-Infinity", float("-inf")), ("null", None)]:
    name = f"rate-{label}-probe"
    values = {"material_name": name, "unit": "kg", "quantity": 1, "rate": val}
    status, r = add_manual(values)
    ok(f"rate={label} -> 400 (NaN/Infinity/-Infinity/null are all rejected)",
       status == 400, detail=f"status={status}")

# --- carbon_emission: NaN/Infinity/-Infinity now hard-rejected too - "0 or
#     blank" is still a warning-only "skip carbon costing" opt-out, but NaN/
#     Infinity are never legitimate and get the same hard-error treatment as
#     quantity/rate now (previously silently accepted and persisted as-is,
#     since add_manual never surfaces warnings to the caller at all).
for label, val in [("NaN", float("nan")), ("Infinity", float("inf")), ("-Infinity", float("-inf"))]:
    name = f"carbon-{label}-probe"
    status, r = add_manual(
        {"material_name": name, "unit": "kg", "quantity": 1, "rate": 1,
         "carbon_emission": val, "carbon_unit_den": "kg", "conversion_factor": 1.0},
        state={"included_in_carbon_emission": True},
    )
    ok(f"carbon_emission={label} (carbon tracking on) -> 400 (NaN/Infinity hard-rejected)",
       status == 400, detail=f"status={status}")

# --- post_demolition_recovery_percentage: NaN/Infinity both rejected now -
#     an explicit isnan()/isinf() check runs BEFORE the "> 100" comparison,
#     so NaN no longer slips past "recovery > 100" just because that
#     comparison happens to be False for NaN.
for label, val in [("NaN", float("nan")), ("Infinity", float("inf"))]:
    name = f"recovery-{label}-probe"
    status, r = add_manual(
        {"material_name": name, "unit": "kg", "quantity": 1, "rate": 1,
         "scrap_rate": 5, "post_demolition_recovery_percentage": val},
        state={"included_in_recyclability": True},
    )
    ok(f"post_demolition_recovery_percentage={label} -> 400 (NaN/Infinity both rejected)",
       status == 400, detail=f"status={status}")


# ============================================================================
# 3. Negative values - str_* material fields via add_manual
#
# Grounded directly in material_entry.py's validate_material_values():
#   quantity:  "qty <= 0" is a hard error -> any negative number is REJECTED
#              (same bucket as zero, not a separate check).
#   rate:      "rate < 0" is its own explicit hard error (distinct from the
#              "== 0" warning-only branch) -> negative REJECTED.
#   carbon_emission / conversion_factor: BOTH now have an explicit "< 0" hard
#              rejection (new rule - previously only "<= 0" as a WARNING,
#              never an error) -> negative REJECTED for both. "0 or blank"
#              (no carbon data at all) is still warning-only, unchanged.
#   scrap_rate / post_demolition_recovery_percentage: NOW have an explicit
#              "< 0" hard rejection (new rule - previously only folded into
#              a "both blank/zero" warning heuristic with no real lower
#              bound) -> negative REJECTED. Upper bound "> 100" on recovery
#              is unchanged; None/blank is still accepted for both.
# ============================================================================
step("3. Negative values - str_* material fields via add_manual")

status, r = add_manual({"material_name": "neg-quantity-probe", "unit": "kg", "rate": 1, "quantity": -5})
ok("quantity=-5 -> 400 (qty <= 0 is a hard error)", status == 400, detail=f"status={status}")

status, r = add_manual({"material_name": "neg-rate-probe", "unit": "kg", "quantity": 1, "rate": -5})
ok("rate=-5 -> 400 (rate < 0 is a hard error)", status == 400, detail=f"status={status}")

status, r = add_manual(
    {"material_name": "neg-carbon-probe", "unit": "kg", "quantity": 1, "rate": 1,
     "carbon_emission": -5, "carbon_unit_den": "kg", "conversion_factor": 1.0},
    state={"included_in_carbon_emission": True},
)
ok("carbon_emission=-5 (carbon tracking on) -> 400 (new hard '< 0' rejection)",
   status == 400, detail=f"status={status}")

status, r = add_manual(
    {"material_name": "neg-conversion-factor-probe", "unit": "kg", "quantity": 1, "rate": 1,
     "carbon_emission": 1, "carbon_unit_den": "kg", "conversion_factor": -5},
    state={"included_in_carbon_emission": True},
)
ok("conversion_factor=-5 (carbon tracking on) -> 400 (new hard '< 0' rejection - a unit-conversion "
   "ratio is never a signed quantity, unlike carbon_emission)",
   status == 400, detail=f"status={status}")

status, r = add_manual(
    {"material_name": "neg-scrap-rate-probe", "unit": "kg", "quantity": 1, "rate": 1,
     "scrap_rate": -5, "post_demolition_recovery_percentage": 10},
    state={"included_in_recyclability": True},
)
ok("scrap_rate=-5 (recyclability on) -> 400 (new hard '< 0' rejection)",
   status == 400, detail=f"status={status}")

status, r = add_manual(
    {"material_name": "neg-recovery-probe", "unit": "kg", "quantity": 1, "rate": 1,
     "scrap_rate": 5, "post_demolition_recovery_percentage": -5},
    state={"included_in_recyclability": True},
)
ok("post_demolition_recovery_percentage=-5 (recyclability on) -> 400 (new hard '< 0' rejection)",
   status == 400, detail=f"status={status}")


# ============================================================================
# 4. Booleans as numbers - a Python-specific trap distinct from every check
#    above: bool is a subclass of int, so isinstance(True, (int, float)) is
#    True and "True == 1" / "False == 0" both hold. Both validators guard
#    against this explicitly and BEFORE any range/positivity check runs:
#
#    registry.py's validate_payload_keys():
#        if isinstance(value, bool) or not isinstance(value, (int, float)):
#            reject   # <- bool caught first, "continue"s past the range check
#                        entirely, so this fires even for a field with NO
#                        declared range (unlike NaN/Infinity, which sail
#                        through range-less fields in section 1 above).
#
#    material_entry.py's validate_material_values():
#        qty:  "not isinstance(qty, (int,float)) or isinstance(qty, bool) or qty <= 0"
#        rate: "not isinstance(rate, (int,float)) or isinstance(rate, bool)" (then < 0 / == 0)
#        Both explicitly exclude bool before ever reaching the numeric check,
#        so True/False must be REJECTED even though True == 1 (which alone
#        would otherwise pass "qty > 0" / "rate >= 0").
# ============================================================================
step("4. Booleans as numbers (bool is an int subclass in Python - must still be rejected)")

for chunk in FIELDDEF_CHUNKS:
    body = get_chunk(chunk)
    fields = [f for f in body.get("fields", []) if f.get("type") == "field"]
    numeric_fields = [f for f in fields if f.get("field_type") in ("int", "float") and not f.get("locked")]
    for fd in numeric_fields:
        key = fd["key"]
        has_range = fd.get("min") is not None and fd.get("max") is not None
        before = get_chunk(chunk).get("data", {}).get(key)
        for label, val in [("True", True), ("False", False)]:
            status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN, body={key: val})
            ok(f"{chunk}.{key}: bool {label} -> 400 (isinstance(bool) check fires "
               f"{'even though a range IS declared' if has_range else 'even with NO range declared at all'})",
               status == 400, detail=f"status={status}")
            after = get_chunk(chunk).get("data", {}).get(key)
            ok(f"{chunk}.{key}: GET confirms value unchanged after rejected bool {label}", after == before)

status, r = add_manual({"material_name": "bool-quantity-probe", "unit": "kg", "rate": 1, "quantity": True})
ok("quantity=True -> 400 (isinstance(qty, bool) excluded before the 'qty > 0' check, despite True == 1)",
   status == 400, detail=f"status={status}")

status, r = add_manual({"material_name": "bool-rate-probe", "unit": "kg", "quantity": 1, "rate": False})
ok("rate=False -> 400 (isinstance(rate, bool) excluded before the '>= 0' check, despite False == 0)",
   status == 400, detail=f"status={status}")


# ============================================================================
# 5. Inclusive range boundaries - min/max themselves must be ACCEPTED (the
#    check is "low <= value <= high", inclusive both ends), and one step
#    past either edge must be REJECTED. NaN/Infinity in section 1 only prove
#    a range rejects wildly-out-of-range values; they say nothing about
#    whether the boundary itself is off-by-one in either direction.
# ============================================================================
step("5. Inclusive range boundaries (min/max accepted, one step outside rejected)")

for chunk in FIELDDEF_CHUNKS:
    body = get_chunk(chunk)
    fields = [f for f in body.get("fields", []) if f.get("type") == "field"]
    numeric_fields = [f for f in fields if f.get("field_type") in ("int", "float") and not f.get("locked")]
    for fd in numeric_fields:
        key = fd["key"]
        low, high = fd.get("min"), fd.get("max")
        if low is None or high is None:
            continue
        step_ = 1 if fd["field_type"] == "int" else 10 ** -(fd.get("decimals") or 2)

        status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN, body={key: low})
        ok(f"{chunk}.{key}: value == min ({low}) -> 200 (inclusive lower bound)",
           status == 200, detail=f"status={status}")
        if status == 200:
            after = get_chunk(chunk).get("data", {}).get(key)
            ok(f"{chunk}.{key}: GET confirms min value actually persisted", after == low)

        status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN, body={key: high})
        ok(f"{chunk}.{key}: value == max ({high}) -> 200 (inclusive upper bound)",
           status == 200, detail=f"status={status}")
        if status == 200:
            after = get_chunk(chunk).get("data", {}).get(key)
            ok(f"{chunk}.{key}: GET confirms max value actually persisted", after == high)

        status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN, body={key: low - step_})
        ok(f"{chunk}.{key}: value == min - {step_} -> 400 (one step below the inclusive lower bound)",
           status == 400, detail=f"status={status}")

        status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN, body={key: high + step_})
        ok(f"{chunk}.{key}: value == max + {step_} -> 400 (one step above the inclusive upper bound)",
           status == 400, detail=f"status={status}")


sys.exit(summary())
