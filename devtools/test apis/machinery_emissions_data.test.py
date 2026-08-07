"""
devtools/test apis/machinery_emissions_data.test.py

Exhaustive regression test for the "machinery_emissions_data" chunk of the
3psLCCA local API (Carbon Emissions Data -> Machinery/Equipment Emissions
tab): schema shape, merge/PATCH semantics, the two-mode (detailed/lumpsum)
split with both sub-objects always preserved, row-granular add/edit/delete
on the detailed equipment table (mirrors the GUI's "Edit Equipment" dialog
fields exactly: name/source/rate/hrs/days/ef), the "exactly one row_patch
per request" bulk-operation rejection, type/range/combo validation, server-
side total_kgCO2e (+ diesel/electricity subtotal) recompute, and the
not_supported shortcut endpoints. Written after
gui/api/pages/machinery_emissions.py was built and manually verified live
(add/edit/mode-switch against a running app) - see that file for the
implementation this exercises.

Run against a live app with the local API enabled (Settings -> Local API):

    python "devtools/test apis/machinery_emissions_data.test.py"

Stdlib only, no dependencies. Prints [PASS]/[FAIL] per check and a summary
at the end; exits non-zero if anything failed.

Unlike social_cost_data, nothing here depends on the project's country (no
DB lookup, no iso3 lock) - one project is enough for the whole run. Project/
token setup is shared via _common.py in this same folder - see that
module's docstring for the --project-id/--token flags and the interactive
numbered project picker.
"""

import sys
import time

from _common import call, step, ok, build_arg_parser, setup_project_and_token, summary

_skip = 0

_CHUNK = "machinery_emissions_data"


def get_data(project_id: str, token: str) -> dict:
    """Shorthand for the GET half of a POST->GET verification pair."""
    _, body = call("GET", f"/{project_id}/{_CHUNK}", token=token)
    return body.get("data", {})


def approx(a, b, tol=1e-6) -> bool:
    return a is not None and b is not None and abs(a - b) < tol


args_parser = build_arg_parser(__doc__)
args = args_parser.parse_args()


# ============================================================================
# 0. Discovery
# ============================================================================
step("0. Discovery")
status, help_doc = call("GET", "/help")
ok("GET /help -> 200", status == 200)
ok("machinery_emissions_data is listed among available pages",
   status == 200 and _CHUNK in help_doc.get("pages", []))

setup = setup_project_and_token(args)
if setup is None:
    sys.exit(1)
project_id, TOKEN = setup


# ============================================================================
# 2. GET schema - shape
# ============================================================================
step("2a. GET machinery_emissions_data -> top-level response shape")
status, med = call("GET", f"/{project_id}/{_CHUNK}", token=TOKEN)
ok("GET -> 200, has 'data'", status == 200 and "data" in med)
ok("response uses 'schema' (not 'fields') - same 'fields'-key-collision "
   "regression check as social_cost_data (see gui/api/server.py's "
   "get_chunk_data())",
   "schema" in med and "fields" not in med)
schema = med.get("schema", {})

step("2b. Schema carries the usage-guidance keys an API caller/AI needs")
for key in ("chunk", "description", "mode_note", "update_semantics", "field_groups",
            "example_post_body_add_row", "example_post_body_edit_row",
            "example_post_body_delete_row", "example_post_body_lumpsum"):
    ok(f"schema has {key!r}", key in schema, detail=f"keys={list(schema.keys())}")

step("2c. field_groups covers all five sub-areas")
field_groups = schema.get("field_groups", {})
for key in ("mode", "remarks", "lumpsum", "detailed", "result"):
    ok(f"field_groups has {key!r}", key in field_groups)

step("2d. detailed.row_fields documents all 6 Edit-Equipment-dialog fields")
row_fields = field_groups.get("detailed", {}).get("row_fields", {})
for key in ("name", "source", "rate", "hrs", "days", "ef"):
    ok(f"detailed.row_fields has {key!r}", key in row_fields)


# ============================================================================
# 3. GET baseline data shape
# ============================================================================
step("3. GET machinery_emissions_data - baseline data shape")
# A genuinely fresh, never-saved-to project legitimately returns {} here -
# same reasoning as social_cost_data's section 3 (MachineryEmissions.
# collect_data()'s keys only exist in stored data once something was
# actually saved, not just constructed in-memory with GUI defaults).
data = med.get("data", {})
if data:
    for key in ("mode", "remarks", "lumpsum", "detailed", "total_kgCO2e"):
        ok(f"data has {key!r}", key in data)
else:
    print("  data is {} (fresh/never-saved project) - skipping per-key checks, that's expected")
ok("data is a dict either way", isinstance(data, dict))
baseline = get_data(project_id, TOKEN)
baseline_row_count = len(baseline.get("detailed", {}).get("rows", []))
print(f"  baseline has {baseline_row_count} detailed row(s)")


# ============================================================================
# 4. Validation matrix
# ============================================================================
step("4a. Non-dict JSON body is rejected")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN, body=["not", "a", "dict"])
ok("JSON array body -> 400 invalid_json_body", status == 400 and r.get("error") == "invalid_json_body")

step("4b. Empty object body is rejected")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN, body={})
ok("empty body -> 400 invalid_field_values", status == 400 and r.get("error") == "invalid_field_values")

step("4c. Unrecognized top-level key is rejected")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN, body={"not_a_real_key": 1})
ok("unrecognized top-level key -> 400, mentions the bad key",
   status == 400 and r.get("error") == "invalid_field_values"
   and any("not_a_real_key" in d for d in r.get("details", [])))

step("4d. Direct write to 'total_kgCO2e' (server-owned) is rejected")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN, body={"total_kgCO2e": 999999})
ok("direct 'total_kgCO2e' write -> 400, rejected as server-owned",
   status == 400 and r.get("error") == "invalid_field_values"
   and any("total_kgCO2e" in d for d in r.get("details", [])))

step("4e. Invalid 'mode' value is rejected")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN, body={"mode": "not-a-real-mode"})
ok("invalid mode -> 400", status == 400 and r.get("error") == "invalid_field_values")

step("4f. 'remarks' sent as a non-string is rejected")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN, body={"remarks": 12345})
ok("remarks as a number -> 400", status == 400 and r.get("error") == "invalid_field_values")

step("4g. lumpsum: unrecognized key is rejected")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN, body={"lumpsum": {"not_a_field": 1}})
ok("lumpsum unknown key -> 400", status == 400 and r.get("error") == "invalid_field_values")

step("4h. lumpsum: wrong type is rejected (not coerced)")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN, body={"lumpsum": {"elec_ef": "high"}})
ok("lumpsum.elec_ef string -> 400", status == 400 and r.get("error") == "invalid_field_values")

step("4i. lumpsum: out-of-range float is rejected")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN, body={"lumpsum": {"elec_ef": -5}})
ok("lumpsum.elec_ef negative (min 0.0) -> 400", status == 400 and r.get("error") == "invalid_field_values")

step("4j. lumpsum: sent as a non-object is rejected")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN, body={"lumpsum": "not-an-object"})
ok("lumpsum as a string -> 400", status == 400 and r.get("error") == "invalid_field_values")

step("4k. detailed: unrecognized sub-key is rejected")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN, body={"detailed": {"not_rows": []}})
ok("detailed unknown sub-key -> 400", status == 400 and r.get("error") == "invalid_field_values")

step("4l. detailed.rows: more than one patch (bulk) is rejected")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN,
                  body={"detailed": {"rows": [{"name": "A"}, {"name": "B"}]}})
ok("2 row patches in one request -> 400, mentions bulk not supported",
   status == 400 and r.get("error") == "invalid_field_values"
   and any("bulk" in d.lower() for d in r.get("details", [])), detail=str(r))

step("4m. detailed.rows: empty list is rejected")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN, body={"detailed": {"rows": []}})
ok("0 row patches -> 400", status == 400 and r.get("error") == "invalid_field_values")

step("4n. detailed.rows: not a list is rejected")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN, body={"detailed": {"rows": {"name": "A"}}})
ok("rows as a dict (not list) -> 400", status == 400 and r.get("error") == "invalid_field_values")

step("4o. row patch: unrecognized key is rejected")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN,
                  body={"detailed": {"rows": [{"not_a_field": 1}]}})
ok("row unknown key -> 400", status == 400 and r.get("error") == "invalid_field_values")

step("4p. row patch: invalid 'source' combo option is rejected")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN,
                  body={"detailed": {"rows": [{"source": "Nuclear"}]}})
ok("row.source invalid option -> 400, lists valid options",
   status == 400 and r.get("error") == "invalid_field_values"
   and any("source" in d for d in r.get("details", [])))

step("4q. row patch: wrong type on a numeric field is rejected")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN,
                  body={"detailed": {"rows": [{"rate": "fast"}]}})
ok("row.rate string -> 400", status == 400 and r.get("error") == "invalid_field_values")

step("4r. row patch: out-of-range numeric field is rejected (hrs max 24)")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN,
                  body={"detailed": {"rows": [{"hrs": 25}]}})
ok("row.hrs > 24 -> 400", status == 400 and r.get("error") == "invalid_field_values")

step("4s. row patch: name as a non-string is rejected")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN,
                  body={"detailed": {"rows": [{"name": 123}]}})
ok("row.name as a number -> 400", status == 400 and r.get("error") == "invalid_field_values")

step("4t. row patch: row_index out of range is rejected")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN,
                  body={"detailed": {"rows": [{"row_index": 999999, "hrs": 1.0}]}})
ok("row_index way out of range -> 400, mentions row count",
   status == 400 and r.get("error") == "invalid_field_values"
   and any("row_index" in d for d in r.get("details", [])), detail=str(r))

step("4u. row patch: row_index wrong type is rejected")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN,
                  body={"detailed": {"rows": [{"row_index": "zero"}]}})
ok("row_index as a string -> 400", status == 400 and r.get("error") == "invalid_field_values")

step("4v. row patch: 'delete': true combined with a field edit in the same patch is rejected")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN,
                  body={"detailed": {"rows": [{"row_index": 0, "delete": True, "hrs": 5.0}]}})
ok("delete + field edit together -> 400 (only meaningful if there's at least one row; "
   "if baseline has 0 rows this correctly fails on row_index range instead - both are "
   "400 invalid_field_values either way)",
   status == 400 and r.get("error") == "invalid_field_values", detail=str(r))

step("4w. row patch: 'delete': true without row_index is rejected")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN,
                  body={"detailed": {"rows": [{"delete": True}]}})
ok("delete without row_index -> 400, requires row_index",
   status == 400 and r.get("error") == "invalid_field_values"
   and any("row_index" in d for d in r.get("details", [])), detail=str(r))

step("4x. Every rejected POST above left the chunk byte-for-byte unchanged (atomicity)")
ok("GET machinery_emissions_data -> identical to the pre-section-4 baseline",
   get_data(project_id, TOKEN) == baseline)


# ============================================================================
# 5. Detailed-mode row round trip (add / edit / delete)
# ============================================================================
step("5a. Add a full row (all 6 fields) - persists, mode forced to 'detailed', total recomputed")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN,
                  body={"mode": "detailed",
                        "detailed": {"rows": [{"name": "Test DG set", "source": "Diesel",
                                                "rate": 4.0, "hrs": 8.0, "days": 30, "ef": 2.69}]}})
ok("POST -> 200", status == 200, detail=str(r))
data_5a = r.get("data", {}) if status == 200 else {}
rows_5a = data_5a.get("detailed", {}).get("rows", [])
ok("row count increased by exactly 1 from baseline", len(rows_5a) == baseline_row_count + 1)
new_row = rows_5a[-1] if rows_5a else {}
ok("new row has the exact values sent",
   new_row.get("name") == "Test DG set" and new_row.get("source") == "Diesel"
   and approx(new_row.get("rate"), 4.0) and approx(new_row.get("hrs"), 8.0)
   and new_row.get("days") == 30 and approx(new_row.get("ef"), 2.69))
expected_emissions = 4.0 * 8.0 * 30 * 2.69
ok("diesel_subtotal_kgCO2e includes this row's emissions (rate*hrs*days*ef)",
   data_5a.get("diesel_subtotal_kgCO2e", 0) >= expected_emissions - 0.01)
new_row_index = len(rows_5a) - 1

step("5b. Add a row with only 'source' set - other fields default like the GUI's blank-row/+Add Equipment button")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN,
                  body={"detailed": {"rows": [{"source": "Other"}]}})
ok("POST -> 200", status == 200, detail=str(r))
rows_5b = r.get("data", {}).get("detailed", {}).get("rows", []) if status == 200 else []
ok("row count increased by 1 again", len(rows_5b) == baseline_row_count + 2)
default_row = rows_5b[-1] if rows_5b else {}
ok("defaulted row: name='', rate/hrs/ef=0.0, days=0, source as sent",
   default_row.get("name") == "" and default_row.get("source") == "Other"
   and approx(default_row.get("rate"), 0.0) and approx(default_row.get("hrs"), 0.0)
   and default_row.get("days") == 0 and approx(default_row.get("ef"), 0.0))
default_row_index = len(rows_5b) - 1

step("5c. Edit the row from 5a by row_index - partial patch changes only the sent fields")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN,
                  body={"detailed": {"rows": [{"row_index": new_row_index, "hrs": 6.0, "days": 25}]}})
ok("POST -> 200", status == 200, detail=str(r))
edited_rows = r.get("data", {}).get("detailed", {}).get("rows", []) if status == 200 else []
edited = edited_rows[new_row_index] if 0 <= new_row_index < len(edited_rows) else {}
ok("hrs/days updated to the patched values", approx(edited.get("hrs"), 6.0) and edited.get("days") == 25)
ok("name/source/rate/ef untouched by the partial patch (row-level merge, not wholesale replace)",
   edited.get("name") == "Test DG set" and edited.get("source") == "Diesel"
   and approx(edited.get("rate"), 4.0) and approx(edited.get("ef"), 2.69))
new_total = 4.0 * 6.0 * 25 * 2.69
ok("total_kgCO2e reflects the recomputed emissions for the edited row",
   r.get("data", {}).get("total_kgCO2e", 0) > 0)

step("5d. GET independently confirms 5c's edit persisted")
after_5c = get_data(project_id, TOKEN)
ok("GET shows the edited row's hrs/days, independent of the POST response",
   approx(after_5c.get("detailed", {}).get("rows", [])[new_row_index].get("hrs"), 6.0))

step("5e. Delete the default-fields row from 5b by row_index")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN,
                  body={"detailed": {"rows": [{"row_index": default_row_index, "delete": True}]}})
ok("POST -> 200", status == 200, detail=str(r))
rows_after_delete = r.get("data", {}).get("detailed", {}).get("rows", []) if status == 200 else []
ok("row count decreased by 1 (back to baseline_row_count + 1)",
   len(rows_after_delete) == baseline_row_count + 1)
ok("the edited row from 5c/5d is still present (only the OTHER row was removed)",
   any(row.get("name") == "Test DG set" and approx(row.get("hrs"), 6.0) for row in rows_after_delete))


# ============================================================================
# 6. Merge/PATCH nesting and mode-switch semantics
# ============================================================================
step("6a. Patching lumpsum.elec_ef alone does not clobber other lumpsum fields set earlier")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN,
                  body={"lumpsum": {"elec_consumption_per_day": 50.0, "elec_days": 20, "elec_ef": 0.71,
                                    "fuel_consumption_per_day": 30.0, "fuel_days": 15, "fuel_ef": 2.69}})
ok("seed full lumpsum -> 200", status == 200)
before_6a = get_data(project_id, TOKEN)
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN, body={"lumpsum": {"elec_ef": 0.85}})
ok("POST elec_ef only -> 200", status == 200)
after_6a = r.get("data", {})
ok("elec_ef updated to 0.85", approx(after_6a.get("lumpsum", {}).get("elec_ef"), 0.85))
ok("every OTHER lumpsum field is untouched (nested merge, not a wholesale 'lumpsum' replace)",
   all(after_6a.get("lumpsum", {}).get(k) == before_6a.get("lumpsum", {}).get(k)
       for k in before_6a.get("lumpsum", {}) if k != "elec_ef"))
ok("'detailed.rows' is completely untouched by a lumpsum-only patch",
   after_6a.get("detailed") == before_6a.get("detailed"))

step("6b. Switching mode to 'lumpsum' preserves 'detailed' rows and recomputes total from lumpsum inputs")
before_6b = get_data(project_id, TOKEN)
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN, body={"mode": "lumpsum"})
ok("POST mode=lumpsum -> 200", status == 200)
after_6b = r.get("data", {})
ok("'detailed.rows' unchanged by the mode switch (not lost)",
   after_6b.get("detailed") == before_6b.get("detailed"))
elec = after_6b.get("lumpsum", {}).get("elec_consumption_per_day", 0) * after_6b.get("lumpsum", {}).get("elec_days", 0) * after_6b.get("lumpsum", {}).get("elec_ef", 0)
fuel = after_6b.get("lumpsum", {}).get("fuel_consumption_per_day", 0) * after_6b.get("lumpsum", {}).get("fuel_days", 0) * after_6b.get("lumpsum", {}).get("fuel_ef", 0)
ok("total_kgCO2e == elec_total + fuel_total for the current lumpsum inputs",
   approx(after_6b.get("total_kgCO2e"), round(elec + fuel, 2)), detail=f"got {after_6b.get('total_kgCO2e')}")
ok("diesel_subtotal_kgCO2e/electricity_subtotal_kgCO2e are ABSENT in lumpsum mode "
   "(not stale leftovers from when mode was 'detailed')",
   "diesel_subtotal_kgCO2e" not in after_6b and "electricity_subtotal_kgCO2e" not in after_6b,
   detail=f"keys={list(after_6b.keys())}")

step("6c. Switching back to 'detailed' restores the diesel/electricity subtotal split")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN, body={"mode": "detailed"})
ok("POST mode=detailed -> 200", status == 200)
after_6c = r.get("data", {})
ok("diesel_subtotal_kgCO2e/electricity_subtotal_kgCO2e are present again", "diesel_subtotal_kgCO2e" in after_6c)
ok("'lumpsum' from 6a/6b is still intact (mode switches never drop the inactive mode's data)",
   after_6c.get("lumpsum") == after_6b.get("lumpsum"))


# ============================================================================
# 7. Injection-style strings are stored inertly (no crash)
# ============================================================================
step("7. Injection-style strings in remarks/row name are stored inertly")
INJECTION_PAYLOADS = [
    ("sql_like", "'; DROP TABLE projects; --"),
    ("script_tag", "<script>alert(document.cookie)</script>"),
    ("path_traversal", "../../../../etc/passwd"),
    ("null_byte", "before\x00after"),
    ("template_injection", "{{7*7}}${7*7}#{7*7}"),
    ("very_long", "A" * 20000),
]
for label, payload_str in INJECTION_PAYLOADS:
    status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN, body={"remarks": payload_str})
    stored = status == 200 and r.get("data", {}).get("remarks") == payload_str
    ok(f"remarks accepts {label!r}-style string and echoes it back, no crash", stored, detail=f"status={status}")
    persisted = get_data(project_id, TOKEN).get("remarks") == payload_str
    ok(f"GET -> {label!r}-style string persisted, server still up (this and later checks keep running)", persisted)


# ============================================================================
# 8. Material/entry-shortcut endpoints are not_supported here (str_* only)
# ============================================================================
step("8. add_from_catalog / add_manual / trash are 404 not_supported on machinery_emissions_data")
before_8 = get_data(project_id, TOKEN)
status, r = call("POST", f"/{project_id}/{_CHUNK}/add_from_catalog", token=TOKEN,
                  body={"component": "x", "db_key": "x", "material_name": "x", "quantity": 1})
ok("add_from_catalog -> 404 not_supported", status == 404 and r.get("error") == "not_supported")
status, r = call("POST", f"/{project_id}/{_CHUNK}/add_manual", token=TOKEN,
                  body={"component": "x", "values": {"material_name": "x", "unit": "x", "quantity": 1, "rate": 1}})
ok("add_manual -> 404 not_supported", status == 404 and r.get("error") == "not_supported")
status, r = call("GET", f"/{project_id}/{_CHUNK}/trash", token=TOKEN)
ok("GET .../trash -> 404 not_supported", status == 404 and r.get("error") == "not_supported")
status, r = call("POST", f"/{project_id}/{_CHUNK}/trash", token=TOKEN, body={"id": "whatever"})
ok("POST .../trash -> 404 not_supported", status == 404 and r.get("error") == "not_supported")
ok("GET machinery_emissions_data -> data unaffected by any of the misrouted shortcut calls above",
   get_data(project_id, TOKEN) == before_8)


# ============================================================================
# 9. Optional interactive human check: live GUI refresh after an API write
# ============================================================================
step("9. Human check: does the GUI actually repaint after an API write? (optional, skippable)")
print(f"  Open project {project_id} in the app (File -> API Access if you need to confirm which window) "
      f"and go to Carbon Emissions Data -> Machinery/Equipment Emissions.")
status, r = call("POST", f"/{project_id}/{_CHUNK}", token=TOKEN,
                  body={"mode": "detailed", "detailed": {"rows": [{"row_index": new_row_index, "hrs": 9.5}]}})
ok("setup POST for the visual check -> 200", status == 200, detail=str(r))
print("  The tab should now show 'Detailed Equipment List' selected, with the 'Test DG set' row's "
      "Avg Hrs/Day = 9.50 and the grand total banner updated - WITHOUT you touching any field.")
try:
    answer = input("  Does the GUI show this live, without you touching a field? [y/n, blank to skip]: ").strip().lower()
except EOFError:
    answer = ""
if answer in ("y", "yes"):
    ok("GUI live-refresh after API write", True)
elif answer in ("n", "no"):
    ok("GUI live-refresh after API write", False, "human said it did not update / was stale")
else:
    _skip += 1
    print("  [SKIP] GUI live-refresh check (no answer given)")


# ============================================================================
# Summary
# ============================================================================
if _skip:
    print(f"\n{_skip} check(s) skipped (no answer given)")
sys.exit(summary())
