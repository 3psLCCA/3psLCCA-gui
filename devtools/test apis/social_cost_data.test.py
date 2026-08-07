"""
devtools/test apis/social_cost_data.test.py

Exhaustive regression test for the "social_cost_data" chunk of the 3psLCCA
local API (Carbon Emissions Data -> Social Cost of Carbon tab): schema shape
and token-friendliness, merge/PATCH semantics, type/range/combo validation,
the two-mode (Ricke/Custom) required-field split, server-side result
recompute, the SCC-database "no data for this combination" rejection
(including the underlying pickle's malformed-"NA"-string cells), the
auto-lock/fallback behavior of "ricke.iso3", and the not_supported shortcut
endpoints. Written after `POST .../social_cost_data` and its validation/
recompute/iso3-lock logic were built and manually verified live - see
gui/api/pages/carbon_emission.py for the implementation this exercises.

Run against a live app with the local API enabled (Settings -> Local API):

    python "devtools/test apis/social_cost_data.test.py"

Stdlib only, no dependencies. Prints [PASS]/[FAIL] per check and a summary
at the end; exits non-zero if anything failed.

Project setup - THREE projects are involved:
  1. A "primary" project (any country - the interactive picker, or
     --project-id) for every country-agnostic check: schema shape, merge
     semantics, type/range/key validation, custom-mode round trip, the
     malformed-DB-cell rejection (confirmed dataset-wide, not just one
     country - see section 4h's comment), not_supported shortcuts.
  2. A dedicated, freshly-created "India" project - India's ISO3 (IND) has
     real rows in the Ricke et al. SCC database, so this project exercises
     the LOCKED branch of "ricke.iso3" (auto-set, caller overrides ignored)
     and lets exact SCC values be hardcoded for regression purposes (see
     section 8's comment on that tradeoff).
  3. A dedicated, freshly-created "Singapore" project - Singapore has NO
     rows in this specific database (confirmed against 238 app countries vs
     ~170 DB-covered ones), so this project exercises the UNLOCKED/fallback
     branch (caller-editable, defaults to "WLD").
Projects 2 and 3 can be supplied via --ricke-project-id/--ricke-token and
--sgp-project-id/--sgp-token to skip creating (and re-consenting to a token
for) a new one every run; otherwise this script creates them itself
(unauthenticated POST /projects/new, same as project_creation.test.py) and
prompts for their tokens interactively.

Project/token setup for the primary project is shared via _common.py in
this same folder - see that module's docstring for the --project-id/--token
flags and the interactive numbered project picker.

PRE-EXISTING BUG, FOUND AND FIXED HERE (2026-08-07) - section 8's
concurrency checks (8c/8d/8e) exist specifically to catch this class of
regression:

  gui/components/utils/common_requested_data.py backs get_currency() /
  get_project_country() / get_project_iso3() (and ~12 other get_*() helpers)
  with a SINGLE module-level global `_controller`. The only call site that
  ever set it was ProjectManager._create_window() in project_manager.py -
  fired once when a project's window is first created in this app process.
  ProjectManager.open_project()'s "already open, just focus it" branch
  (existing.show_project_view()/.raise_()/.activateWindow()) never called
  set_controller() again. So with two project windows open, the global
  stayed pinned to whichever was created MOST RECENTLY, and EVERY get_*()
  call from EITHER window's code - including this API's own "ricke.iso3"
  auto-lock (_resolve_iso3() in gui/api/pages/carbon_emission.py) and
  currency lookup (_result_for()) - could silently read the OTHER window's
  data instead of its own. Not introduced by social_cost_data; a pre-
  existing app-wide bug (affects real GUI code too - currency suffixes,
  country-lock combos, etc. on any widget using common_requested_data) that
  this endpoint's own multi-window testing happened to expose clearly.

  Fixed in two places:
    - gui/api/bridge.py's ApiBridge._find_window() now re-syncs the global
      to the resolved window's own controller before any chunk-specific
      hook runs - every bridge method resolves its target window through
      here, so this fixes every current and future page's API-triggered
      reads generically, with no registry/hook-contract or per-page changes.
    - gui/project_window.py's ProjectWindow.changeEvent() now re-asserts
      itself as the active controller on OS-level window activation (click,
      alt-tab), fixing the equivalent GUI-only case (a human clicking
      between windows with no API involved) - not exercised by this script
      (no way to drive OS window focus from an HTTP test), verify that path
      manually if it's ever in question again.

  Section 8's checks assert the CORRECT desired behavior and passed cleanly
  (twice in a row, for determinism) against the fixed code. If 8c/8d/8e
  start failing again in the future, treat it as this exact regression
  resurfacing, not a break in social_cost_data's own validate/merge/lock
  logic - re-check bridge.py's _find_window() first.
"""

import json
import sys
import time

from _common import (
    call, step, ok, wait_until_open,
    build_arg_parser, setup_project_and_token, get_token, summary,
)

_skip = 0


def get_data(project_id: str, token: str) -> dict:
    """Shorthand for the GET half of a POST->GET verification pair."""
    _, body = call("GET", f"/{project_id}/social_cost_data", token=token)
    return body.get("data", {})


def approx(a, b, tol=1e-6) -> bool:
    return a is not None and b is not None and abs(a - b) < tol


def _create_project_with_country(name_substr: str, label: str) -> tuple[str, str, str] | None:
    """Creates (and opens) a fresh throwaway project whose country's display
    name contains `name_substr` (case-insensitive), matched against the
    real, live GET /projects/new options list rather than a hardcoded exact
    string (the app's exact casing/format for country names is an
    implementation detail this test shouldn't assume). Returns
    (project_id, token, currency), or None if anything along the way
    failed - callers should treat None as "skip the checks that need this
    project" rather than aborting the whole run, same spirit as
    project_creation.test.py's section 7 fallback."""
    status, schema = call("GET", "/projects/new")
    if status != 200:
        print(f"  [{label}] could not fetch /projects/new schema")
        return None
    options = schema.get("fields", {}).get("country", {}).get("options", [])
    match = next((c for c in options if name_substr.lower() in c.lower()), None)
    if match is None:
        print(f"  [{label}] no country option matching {name_substr!r} found - skipping")
        return None

    project_name = f"social_cost_data.test.py [{label}] {time.strftime('%Y-%m-%d %H:%M:%S')}"
    status, created = call("POST", "/projects/new", body={"project_name": project_name, "country": match})
    if status != 200:
        print(f"  [{label}] POST /projects/new failed: {created}")
        return None
    project_id, currency = created["project_id"], created["currency"]
    print(f"  [{label}] created {project_id}  (country={match!r}, currency={currency!r})")

    if not wait_until_open(project_id, f"{label} create"):
        print(f"  [{label}] project did not report open in time")
        return None

    print(f"In the app: File -> API Access -> copy the token for {project_id} ({label}).")
    token = get_token(project_id, None)
    if not token:
        print(f"  [{label}] no token given - skipping checks that need this project")
        return None
    return project_id, token, currency


# A combo confirmed (via the app's own _lookup()/_get_db()) to hit the
# underlying pickle's malformed cells: some "no data" cells for "Fixed 3%"/
# "Fixed 5%" discounting are stored as the literal string "NA" rather than
# NaN, which raises instead of cleanly reporting "no row" - reproduced for
# IND/USA/WLD/CHN/BRA alike, so this is a dataset-wide characteristic, not
# specific to any one country. _ricke_cost()/the "no data" rejection in
# _apply() must treat this the same as a genuinely missing row.
_MALFORMED_CELL_RICKE = {
    "ssp": "SSP2 (Middle of the Road)", "rcp": "Closest RCP (Default)",
    "dmg_func": "BHM SR (Short Run)", "dmg_params": "Estimates (Central Params)",
    "climate_uncertainty": "Expected (Central Projections)",
    "discounting": "Fixed 3%", "percentile": "50.0% (Central)",
}

# A combo confirmed live (this session) to resolve to real DB rows - used
# for every "known good" Ricke-mode check below. iso3 is deliberately
# omitted everywhere it's used - see the auto-lock/fallback checks in
# section 8, which is exactly what this field is for.
_GOOD_RICKE_BASE = {
    "ssp": "SSP1 (Sustainability)", "rcp": "RCP4.5 (≈ +2.5°C in 2100)",
    "dmg_func": "BHM LR (Long Run)", "dmg_params": "Bootstrap (Full Uncertainty)",
    "climate_uncertainty": "Expected (Central Projections)",
    "discounting": "Growth-adjusted (prtp=1%, η=0.7)",
    "percentile": "50.0% (Central)",
}

_SOURCE_RICKE = "K. Ricke et al. (Country-Level)"
_SOURCE_CUSTOM = "Custom / Manual Override"


args_parser = build_arg_parser(__doc__)
args_parser.add_argument("--ricke-project-id", help="reuse an existing India-country project instead of creating one")
args_parser.add_argument("--ricke-token", help="token for --ricke-project-id (skips the interactive prompt)")
args_parser.add_argument("--sgp-project-id", help="reuse an existing Singapore-country project instead of creating one")
args_parser.add_argument("--sgp-token", help="token for --sgp-project-id (skips the interactive prompt)")
args = args_parser.parse_args()


# ============================================================================
# 0. Discovery
# ============================================================================
step("0. Discovery")
status, help_doc = call("GET", "/help")
ok("GET /help -> 200", status == 200)
ok("social_cost_data is listed among available pages",
   status == 200 and "social_cost_data" in help_doc.get("pages", []))

setup = setup_project_and_token(args)
if setup is None:
    sys.exit(1)
project_id, TOKEN = setup


# ============================================================================
# 2. GET schema - shape, and the token-friendliness fixes specifically
# ============================================================================
step("2a. GET social_cost_data -> top-level response shape")
status, scd = call("GET", f"/{project_id}/social_cost_data", token=TOKEN)
ok("GET -> 200, has 'data'", status == 200 and "data" in scd)
ok("response uses 'schema' (not 'fields') - regression check for the "
   "server.py 'fields' key collision that used to silently drop "
   "description/update_semantics/examples (see gui/api/server.py's "
   "get_chunk_data(): a top-level 'fields' key in a hand-written schema "
   "is treated as the flat FieldDef-list shape and everything else is "
   "discarded)",
   "schema" in scd and "fields" not in scd)
schema = scd.get("schema", {})

step("2b. Schema carries the usage-guidance keys an API caller/AI needs (not just field types)")
for key in ("chunk", "description", "source_note", "update_semantics", "field_groups",
            "example_post_body_ricke", "example_post_body_custom"):
    ok(f"schema has {key!r}", key in schema, detail=f"keys={list(schema.keys())}")

step("2c. field_groups covers all four sub-areas")
field_groups = schema.get("field_groups", {})
for key in ("source", "ricke", "custom", "result"):
    ok(f"field_groups has {key!r}", key in field_groups)

step("2d. iso3 field is token-friendly (no giant options list) and documents the auto-lock behavior")
ricke_fields = field_groups.get("ricke", {}).get("fields", [])
iso3_field = next((f for f in ricke_fields if f.get("key") == "iso3"), None)
ok("iso3 field exists in schema", iso3_field is not None)
if iso3_field is not None:
    ok("iso3 field has NO 'options' key (the ~170-code list was removed for token-friendliness)",
       "options" not in iso3_field, detail=f"got keys={list(iso3_field.keys())}")
    ok("iso3 field has a 'note' explaining the auto-lock/fallback behavior",
       "note" in iso3_field and "lock" in iso3_field["note"].lower())

step("2e. Overall schema size stays bounded (crude token-budget regression guard)")
schema_chars = len(json.dumps(schema))
print(f"  schema size: {schema_chars} chars")
ok("schema JSON stays under 12000 chars (was ~9000+ before the iso3 list was trimmed; "
   "catches any future re-introduction of a large enumerated list)",
   schema_chars < 12000, detail=f"got {schema_chars}")

step("2f. Example bodies model the recommended usage (iso3 omitted)")
example_ricke = schema.get("example_post_body_ricke", {})
ok("example_post_body_ricke.ricke does NOT include 'iso3' (models 'omit it, it's auto')",
   "iso3" not in example_ricke.get("ricke", {}))
ok("example_post_body_custom has a 'custom' key with scc_value",
   "scc_value" in schema.get("example_post_body_custom", {}).get("custom", {}))


# ============================================================================
# 3. GET baseline data shape
# ============================================================================
step("3. GET social_cost_data - baseline data shape")
# A genuinely fresh, never-saved-to project legitimately returns {} here (no
# keys at all) - the four sub-keys only exist once something has actually
# been written (matches the GUI: SCCWidget.get_data_dict() only produces
# them when called, which happens on save, not just on page construction).
# So "data has each key" is only asserted for a project already known to
# have prior social_cost_data state - otherwise just confirm GET succeeds
# with SOME dict (possibly empty) and don't assert individual keys.
data = scd.get("data", {})
if data:
    for key in ("source", "ricke", "custom", "result"):
        ok(f"data has {key!r}", key in data)
else:
    print("  data is {} (fresh/never-saved project) - skipping per-key checks, that's expected")
ok("data is a dict either way", isinstance(data, dict))
baseline = get_data(project_id, TOKEN)


# ============================================================================
# 4. Country-agnostic validation matrix (primary project - any country)
# ============================================================================
step("4a. Non-dict JSON body is rejected")
status, r = call("POST", f"/{project_id}/social_cost_data", token=TOKEN, body=["not", "a", "dict"])
ok("JSON array body -> 400 invalid_json_body", status == 400 and r.get("error") == "invalid_json_body")

step("4b. Empty object body is rejected")
status, r = call("POST", f"/{project_id}/social_cost_data", token=TOKEN, body={})
ok("empty body -> 400 invalid_field_values", status == 400 and r.get("error") == "invalid_field_values")

step("4c. Unrecognized top-level key is rejected")
status, r = call("POST", f"/{project_id}/social_cost_data", token=TOKEN, body={"not_a_real_key": 1})
ok("unrecognized top-level key -> 400, mentions the bad key",
   status == 400 and r.get("error") == "invalid_field_values"
   and any("not_a_real_key" in d for d in r.get("details", [])))

step("4d. Direct write to 'result' (server-owned) is rejected")
status, r = call("POST", f"/{project_id}/social_cost_data", token=TOKEN,
                  body={"result": {"cost_of_carbon_local": 999999}})
ok("direct 'result' write -> 400, rejected as server-owned",
   status == 400 and r.get("error") == "invalid_field_values"
   and any("result" in d for d in r.get("details", [])))

step("4e. Invalid 'source' value is rejected")
status, r = call("POST", f"/{project_id}/social_cost_data", token=TOKEN, body={"source": "Not A Real Mode"})
ok("invalid source -> 400", status == 400 and r.get("error") == "invalid_field_values")

step("4f. custom: unrecognized key is rejected")
status, r = call("POST", f"/{project_id}/social_cost_data", token=TOKEN, body={"custom": {"not_a_field": 1}})
ok("custom unknown key -> 400", status == 400 and r.get("error") == "invalid_field_values")

step("4g. custom.scc_value: wrong type is rejected (not coerced)")
status, r = call("POST", f"/{project_id}/social_cost_data", token=TOKEN, body={"custom": {"scc_value": "high"}})
ok("custom.scc_value string -> 400", status == 400 and r.get("error") == "invalid_field_values")

step("4h. custom.scc_value: out-of-range is rejected")
status, r = call("POST", f"/{project_id}/social_cost_data", token=TOKEN, body={"custom": {"scc_value": 99999999}})
ok("custom.scc_value out of range -> 400", status == 400 and r.get("error") == "invalid_field_values")

step("4i. 'custom' sent as a non-object is rejected")
status, r = call("POST", f"/{project_id}/social_cost_data", token=TOKEN, body={"custom": "not-an-object"})
ok("custom as string -> 400", status == 400 and r.get("error") == "invalid_field_values")

step("4j. ricke: unrecognized key is rejected")
status, r = call("POST", f"/{project_id}/social_cost_data", token=TOKEN, body={"ricke": {"not_a_field": 1}})
ok("ricke unknown key -> 400", status == 400 and r.get("error") == "invalid_field_values")

step("4k. ricke: invalid combo option is rejected")
status, r = call("POST", f"/{project_id}/social_cost_data", token=TOKEN, body={"ricke": {"ssp": "not-an-option"}})
ok("ricke.ssp invalid option -> 400, lists valid options",
   status == 400 and r.get("error") == "invalid_field_values"
   and any("ssp" in d for d in r.get("details", [])))

step("4l. ricke: float field given wrong type is rejected")
status, r = call("POST", f"/{project_id}/social_cost_data", token=TOKEN, body={"ricke": {"cpi_ratio": "one point one"}})
ok("ricke.cpi_ratio string -> 400", status == 400 and r.get("error") == "invalid_field_values")

step("4m. ricke: float field out of range is rejected")
status, r = call("POST", f"/{project_id}/social_cost_data", token=TOKEN, body={"ricke": {"cpi_ratio": -5}})
ok("ricke.cpi_ratio negative (min 0.0) -> 400", status == 400 and r.get("error") == "invalid_field_values")

step("4n. ricke.iso3: wrong type is rejected")
status, r = call("POST", f"/{project_id}/social_cost_data", token=TOKEN, body={"ricke": {"iso3": 123}})
ok("ricke.iso3 as a number -> 400", status == 400 and r.get("error") == "invalid_field_values")

step("4o. ricke.iso3: empty string is rejected")
status, r = call("POST", f"/{project_id}/social_cost_data", token=TOKEN, body={"ricke": {"iso3": ""}})
ok("ricke.iso3 empty string -> 400", status == 400 and r.get("error") == "invalid_field_values")

step("4p. Switching to Ricke mode with incomplete fields lists the MISSING FIELD NAMES, not raw keys")
# The primary project may already have a fully-populated "ricke" sub-object
# left over from earlier use (POSTs merge, they don't replace) - sending
# only "ssp" would then merge into already-complete data and succeed
# (200), not fail as intended. Explicitly clear "percentile" (the field
# this check asserts on) to the GUI's own unset-combo placeholder first, so
# the missing-field check is deterministic regardless of prior state.
status, r = call("POST", f"/{project_id}/social_cost_data", token=TOKEN,
                  body={"source": _SOURCE_RICKE,
                        "ricke": {"ssp": "SSP1 (Sustainability)", "percentile": "-- select --"}})
ok("incomplete ricke -> 400, mentions a human-readable field label (e.g. 'Percentile'), not just a raw key",
   status == 400 and r.get("error") == "invalid_field_values"
   and any("Percentile" in d for d in r.get("details", [])), detail=str(r))

step("4q. A combo that hits the underlying pickle's malformed-cell bug is rejected, not silently saved with cost=0")
status, r = call("POST", f"/{project_id}/social_cost_data", token=TOKEN,
                  body={"source": _SOURCE_RICKE, "ricke": _MALFORMED_CELL_RICKE})
ok("malformed-cell combo -> 400, 'no data in the SCC database'",
   status == 400 and r.get("error") == "invalid_field_values"
   and any("no data" in d.lower() for d in r.get("details", [])), detail=str(r))

step("4r. Every rejected POST above left the chunk byte-for-byte unchanged (atomicity)")
ok("GET social_cost_data -> identical to the pre-section-4 baseline",
   get_data(project_id, TOKEN) == baseline)


# ============================================================================
# 5. Custom-mode full round trip (country-agnostic)
# ============================================================================
step("5a. POST custom mode - value, source, comments all persist and 'result' mirrors scc_value")
marker = f"social_cost_data.test.py {time.strftime('%Y-%m-%d %H:%M:%S')}"
status, r = call("POST", f"/{project_id}/social_cost_data", token=TOKEN,
                  body={"source": _SOURCE_CUSTOM, "custom": {"scc_value": 7.25, "source": marker, "comments": "test run"}})
ok("POST -> 200, result.cost_of_carbon_local == scc_value, selected_mode == source",
   status == 200
   and approx(r.get("data", {}).get("result", {}).get("cost_of_carbon_local"), 7.25)
   and r.get("data", {}).get("result", {}).get("selected_mode") == _SOURCE_CUSTOM)
after5a = get_data(project_id, TOKEN)
ok("GET -> custom.scc_value/source/comments persisted independently of the POST response",
   approx(after5a.get("custom", {}).get("scc_value"), 7.25)
   and after5a.get("custom", {}).get("source") == marker
   and after5a.get("custom", {}).get("comments") == "test run")

step("5b. Injection-style strings in custom.source/comments are stored inertly (no crash)")
INJECTION_PAYLOADS = [
    ("sql_like", "'; DROP TABLE projects; --"),
    ("script_tag", "<script>alert(document.cookie)</script>"),
    ("path_traversal", "../../../../etc/passwd"),
    ("null_byte", "before\x00after"),
    ("template_injection", "{{7*7}}${7*7}#{7*7}"),
    ("very_long", "A" * 20000),
]
for label, payload_str in INJECTION_PAYLOADS:
    status, r = call("POST", f"/{project_id}/social_cost_data", token=TOKEN, body={"custom": {"comments": payload_str}})
    stored = status == 200 and r.get("data", {}).get("custom", {}).get("comments") == payload_str
    ok(f"custom.comments accepts {label!r}-style string and echoes it back, no crash", stored, detail=f"status={status}")
    persisted = get_data(project_id, TOKEN).get("custom", {}).get("comments") == payload_str
    ok(f"GET -> {label!r}-style string persisted, server still up (this and later checks keep running)", persisted)

step("5c. Partial patch (only scc_value) auto-recomputes 'result' without resending source/other custom keys")
before_5c = get_data(project_id, TOKEN)
status, r = call("POST", f"/{project_id}/social_cost_data", token=TOKEN, body={"custom": {"scc_value": 42.5}})
ok("POST scc_value only -> 200, result recomputed to the new value automatically",
   status == 200 and approx(r.get("data", {}).get("result", {}).get("cost_of_carbon_local"), 42.5))
ok("comments/source from 5a/5b untouched by this scc_value-only patch (nested merge, not wholesale replace)",
   get_data(project_id, TOKEN).get("custom", {}).get("comments") == before_5c.get("custom", {}).get("comments"))


# ============================================================================
# 6. Merge/PATCH nesting semantics
# ============================================================================
step("6a. Patching custom.comments alone does not clobber custom.scc_value set earlier")
status, r = call("POST", f"/{project_id}/social_cost_data", token=TOKEN, body={"custom": {"comments": "only comments changed"}})
ok("scc_value stays 42.5 after a comments-only patch",
   status == 200 and approx(r.get("data", {}).get("custom", {}).get("scc_value"), 42.5))

step("6b. Patching ricke.* while source is Custom leaves 'custom' untouched and only patches the one ricke field")
before_6b = get_data(project_id, TOKEN)
status, r = call("POST", f"/{project_id}/social_cost_data", token=TOKEN, body={"ricke": {"cpi_ratio": 2.5}})
ok("POST ricke.cpi_ratio only -> 200 (no required-field check runs - source is still Custom)", status == 200)
after_6b = r.get("data", {})
ok("ricke.cpi_ratio updated to 2.5", approx(after_6b.get("ricke", {}).get("cpi_ratio"), 2.5))
ok("every OTHER ricke.* field is untouched (nested merge, not a wholesale 'ricke' replace)",
   all(after_6b.get("ricke", {}).get(k) == before_6b.get("ricke", {}).get(k)
       for k in before_6b.get("ricke", {}) if k != "cpi_ratio"))
ok("'custom' sub-object is completely untouched by a ricke-only patch",
   after_6b.get("custom") == before_6b.get("custom"))
ok("'source' is still Custom (untouched, since this patch never sent 'source')",
   after_6b.get("source") == _SOURCE_CUSTOM)


# ============================================================================
# 7. Material/entry-shortcut endpoints are not_supported here (str_* only)
# ============================================================================
step("7. add_from_catalog / add_manual / trash are 404 not_supported on social_cost_data")
before_7 = get_data(project_id, TOKEN)
status, r = call("POST", f"/{project_id}/social_cost_data/add_from_catalog", token=TOKEN,
                  body={"component": "x", "db_key": "x", "material_name": "x", "quantity": 1})
ok("add_from_catalog -> 404 not_supported", status == 404 and r.get("error") == "not_supported")
status, r = call("POST", f"/{project_id}/social_cost_data/add_manual", token=TOKEN,
                  body={"component": "x", "values": {"material_name": "x", "unit": "x", "quantity": 1, "rate": 1}})
ok("add_manual -> 404 not_supported", status == 404 and r.get("error") == "not_supported")
status, r = call("GET", f"/{project_id}/social_cost_data/trash", token=TOKEN)
ok("GET .../trash -> 404 not_supported", status == 404 and r.get("error") == "not_supported")
status, r = call("POST", f"/{project_id}/social_cost_data/trash", token=TOKEN, body={"id": "whatever"})
ok("POST .../trash -> 404 not_supported", status == 404 and r.get("error") == "not_supported")
ok("GET social_cost_data -> data unaffected by any of the misrouted shortcut calls above",
   get_data(project_id, TOKEN) == before_7)


# ============================================================================
# 8. Dedicated fixed-country projects: iso3 lock/fallback + exact-value
#    regression checks against the real Ricke SCC database.
#
# The numeric expected values below are hardcoded from live runs against
# this app's bundled cscc_db.pkl during development of this endpoint. They
# are exact and deterministic (pure function over a static, bundled
# dataset) - a good regression signal - BUT they will legitimately need
# updating if that pickle is ever regenerated/replaced with different
# underlying SCC estimates. That's an acceptable, understood tradeoff for
# an "exhaustive, catch real breakage" test suite (see this file's own
# request context) - if these specific numbers ever fail, first check
# whether the .pkl changed before assuming the API logic broke.
# ============================================================================
step("8. Setting up dedicated India (Ricke-covered) and Singapore (not covered) projects")
print("  NOTE: 8c/8d/8e guard against a real, previously-found multi-window "
      "global-controller bug (fixed in bridge.py's _find_window() - see this "
      "file's module docstring, 'PRE-EXISTING BUG, FOUND AND FIXED HERE') - "
      "a failure here means that regression resurfaced, not a break in "
      "social_cost_data's own logic.")
if args.ricke_project_id:
    print(f"  reusing --ricke-project-id {args.ricke_project_id}")
    if not ok("India-project (--ricke-project-id) is reachable",
              call("GET", f"/{args.ricke_project_id}/general_info", token=args.ricke_token)[0] != 404):
        india = None
    else:
        india = (args.ricke_project_id, args.ricke_token, None)
else:
    india = _create_project_with_country("india", "india")

if args.sgp_project_id:
    print(f"  reusing --sgp-project-id {args.sgp_project_id}")
    if not ok("Singapore-project (--sgp-project-id) is reachable",
              call("GET", f"/{args.sgp_project_id}/general_info", token=args.sgp_token)[0] != 404):
        singapore = None
    else:
        singapore = (args.sgp_project_id, args.sgp_token, None)
else:
    singapore = _create_project_with_country("singapore", "singapore")

if india is None:
    print("  [SKIP] section 8's India-locked checks (no usable India project)")
if singapore is None:
    print("  [SKIP] section 8's Singapore-unlocked checks (no usable Singapore project)")

if india is not None:
    india_id, india_token, _ = india

    step("8a. India (Ricke-covered): full combo, iso3 OMITTED -> auto-locks to IND, exact expected cost")
    status, r = call("POST", f"/{india_id}/social_cost_data", token=india_token,
                      body={"source": _SOURCE_RICKE,
                            "ricke": {**_GOOD_RICKE_BASE, "usd_to_local_rate": 83.0, "cpi_ratio": 1.1}})
    ok("POST -> 200", status == 200, detail=str(r))
    ricke_out = r.get("data", {}).get("ricke", {}) if status == 200 else {}
    ok("ricke.iso3 auto-resolved to 'IND' (never sent by this request)", ricke_out.get("iso3") == "IND")
    ok("result.cost_of_carbon_local matches the known-good hardcoded value for this exact combo",
       approx(r.get("data", {}).get("result", {}).get("cost_of_carbon_local"), 18.880057828739627),
       detail=f"got {r.get('data', {}).get('result', {}).get('cost_of_carbon_local')}")
    india_before_lock_test = get_data(india_id, india_token)

    step("8b. India: explicit iso3='USA' override is SILENTLY IGNORED - stays locked to IND")
    status, r = call("POST", f"/{india_id}/social_cost_data", token=india_token, body={"ricke": {"iso3": "USA"}})
    ok("POST -> 200 (not rejected - the override is ignored, not an error)", status == 200)
    ok("ricke.iso3 is STILL 'IND', not 'USA'", r.get("data", {}).get("ricke", {}).get("iso3") == "IND")
    ok("result.cost_of_carbon_local unchanged from 8a (proves the lock, not just the label)",
       approx(r.get("data", {}).get("result", {}).get("cost_of_carbon_local"), 18.880057828739627))

if singapore is not None:
    sgp_id, sgp_token, _ = singapore

    step("8c. Singapore (not in Ricke DB): full combo, iso3 EXPLICITLY CLEARED -> falls back to WLD, exact expected cost")
    # This project persists across reruns of this script (--sgp-project-id
    # reuse) and 8e below deliberately leaves iso3 set to a real value
    # ("GBR") at the end of its own run - so simply OMITTING "iso3" here
    # would just preserve whatever a PRIOR run left behind (correct
    # _resolve_iso3 behavior, not a bug) rather than exercising the "unset"
    # fallback this check is actually about. Explicitly clear it to the
    # GUI's own unset-combo placeholder first, same fix as section 4p.
    status, r = call("POST", f"/{sgp_id}/social_cost_data", token=sgp_token,
                      body={"source": _SOURCE_RICKE,
                            "ricke": {**_GOOD_RICKE_BASE, "iso3": "-- select --",
                                      "usd_to_local_rate": 1.35, "cpi_ratio": 1.1}})
    ok("POST -> 200", status == 200, detail=str(r))
    ok("ricke.iso3 fell back to 'WLD' (not locked - Singapore has no SCC DB row)",
       r.get("data", {}).get("ricke", {}).get("iso3") == "WLD")
    ok("result.cost_of_carbon_local matches the known-good hardcoded WLD value for this combo",
       approx(r.get("data", {}).get("result", {}).get("cost_of_carbon_local"), 3.06781320884497),
       detail=f"got {r.get('data', {}).get('result', {}).get('cost_of_carbon_local')}")

    step("8d. Singapore: explicit iso3='USA' IS respected (unlocked - unlike India in 8b)")
    status, r = call("POST", f"/{sgp_id}/social_cost_data", token=sgp_token, body={"ricke": {"iso3": "USA"}})
    ok("POST -> 200", status == 200)
    ok("ricke.iso3 is now 'USA' exactly as sent", r.get("data", {}).get("ricke", {}).get("iso3") == "USA")
    ok("result.cost_of_carbon_local matches the known-good hardcoded USA value (differs from WLD's, proving a real recompute)",
       approx(r.get("data", {}).get("result", {}).get("cost_of_carbon_local"), 0.6716743610010936),
       detail=f"got {r.get('data', {}).get('result', {}).get('cost_of_carbon_local')}")

if india is not None and singapore is not None:
    step("8e. Concurrency: both India and Singapore open at once - lock/fallback still resolve per-project, "
         "not off a shared 'last focused project' global (this reproduces a scenario manually verified live "
         "during development - see this endpoint's use of common_requested_data.get_project_iso3(), which "
         "is backed by a single process-wide 'active controller' the GUI sets on project focus/open, not "
         "something inherently per-project-id - a regression here would mean that global started leaking "
         "across concurrently open projects)")
    india_id, india_token, _ = india
    sgp_id, sgp_token, _ = singapore
    status, r = call("POST", f"/{india_id}/social_cost_data", token=india_token, body={"ricke": {"iso3": "GBR"}})
    ok("India still locks to IND (ignoring GBR) even with Singapore also open",
       status == 200 and r.get("data", {}).get("ricke", {}).get("iso3") == "IND")
    status, r = call("POST", f"/{sgp_id}/social_cost_data", token=sgp_token, body={"ricke": {"iso3": "GBR"}})
    ok("Singapore still accepts an explicit override (GBR) even with India also open",
       status == 200 and r.get("data", {}).get("ricke", {}).get("iso3") == "GBR")


# ============================================================================
# 9. Optional interactive human check: live GUI refresh after an API write
# ============================================================================
step("9. Human check: does the GUI actually repaint after an API write? (optional, skippable)")
if india is not None:
    india_id, india_token, _ = india
    print(f"  Open project {india_id} in the app (File -> API Access if you need to confirm which window) "
          f"and go to Carbon Emissions Data -> Social Cost of Carbon.")
    status, r = call("POST", f"/{india_id}/social_cost_data", token=india_token,
                      body={"ricke": {"usd_to_local_rate": 91.0}})
    ok("setup POST for the visual check -> 200", status == 200)
    print("  The tab should now show usd_to_local_rate = 91.0 and an updated SCC value/range label "
          "WITHOUT you touching any field.")
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
else:
    _skip += 1
    print("  [SKIP] no India project available for this check")


# ============================================================================
# Summary
# ============================================================================
if _skip:
    print(f"\n{_skip} check(s) skipped (no answer given, or a required project was unavailable)")
sys.exit(summary())
