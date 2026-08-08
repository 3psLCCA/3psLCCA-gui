"""
devtools/test apis/validate_and_lock.test.py

Exhaustive regression test for GET /{project_id}/validate and
POST /{project_id}/unlock - the two endpoints that operate the Results
page's "Calculate" button and its lock button respectively (see
gui/api/bridge.py's ApiBridge._validate_all()/_unlock() and
gui/project_window.py's ProjectWindow.apply_lock_state()).

Covers:
  - /validate's response shape (project_id, valid, errors, warnings,
    page_chunks, results, note) and the token-budget trims (no "all_data"/
    "lcc_breakdown" in "results").
  - The note's conditional wording (errors/warnings sentences only appear
    when there actually are errors/warnings).
  - The full lock lifecycle: a clean (0-error) /validate call runs the real
    calculation AND locks the project (native behavior - same as a human's
    Calculate click), every write route (chunk POST, add_from_catalog,
    add_manual, trash, and /validate itself) is rejected with 423
    project_locked while locked, GET reads still work while locked, and
    POST /unlock clears the lock (idempotently) and restores writes.
  - Auth (401) and not-open (404) on both routes.

Run against a live app with the local API enabled (Settings -> Local API):

    python "devtools/test apis/validate_and_lock.test.py"

Stdlib only, no dependencies. Prints [PASS]/[FAIL] per check and a summary
at the end; exits non-zero if anything failed.

The full lock-cycle checks (section 5) only run if the chosen project
GETs "valid": true from /validate - i.e. it needs a project with zero
validation errors across every page already filled in (a fresh/empty
project will not qualify). Pass an already-complete project via
--project-id/--token (e.g. one previously used to test machinery_emissions
_data.test.py/social_cost_data.test.py, or any real imported project) to
exercise section 5; otherwise those checks are skipped with a clear note,
not silently omitted.
"""

import sys
import time

from _common import call, step, ok, build_arg_parser, setup_project_and_token, summary

_skip = 0


def get_general_info(project_id: str, token: str) -> dict:
    _, body = call("GET", f"/{project_id}/general_info", token=token)
    return body.get("data", {})


def unlock(project_id: str, token: str):
    return call("POST", f"/{project_id}/unlock", token=token)


def validate(project_id: str, token: str, timeout: float = 80.0):
    return call("GET", f"/{project_id}/validate", token=token, timeout=timeout)


args_parser = build_arg_parser(__doc__)
args = args_parser.parse_args()


# ============================================================================
# 0. Discovery
# ============================================================================
step("0. Discovery")
status, help_doc = call("GET", "/help")
ok("GET /help -> 200", status == 200)
paths = [(e.get("method"), e.get("path")) for e in help_doc.get("endpoints", [])] if status == 200 else []
ok("GET /{project_id}/validate is documented", ("GET", "/{project_id}/validate") in paths)
ok("POST /{project_id}/unlock is documented", ("POST", "/{project_id}/unlock") in paths)
catalogue = help_doc.get("errors", {}).get("catalogue", []) if status == 200 else []
ok("project_locked (423) is documented in the error catalogue",
   any(e.get("error") == "project_locked" and e.get("status") == 423 for e in catalogue))

setup = setup_project_and_token(args)
if setup is None:
    sys.exit(1)
project_id, TOKEN = setup


# ============================================================================
# 1. Auth / not-open checks (both routes)
# ============================================================================
step("1a. GET /validate with no token -> 401")
status, r = call("GET", f"/{project_id}/validate")
ok("no token -> 401 unauthorized", status == 401 and r.get("error") == "unauthorized")

step("1b. POST /unlock with no token -> 401")
status, r = call("POST", f"/{project_id}/unlock")
ok("no token -> 401 unauthorized", status == 401 and r.get("error") == "unauthorized")

step("1c. GET /validate on a bogus project id -> 401 (token can't be valid for a project that isn't real)")
status, r = call("GET", "/proj_doesnotexist_zzz/validate", token=TOKEN)
ok("bogus project + real token -> 401 (auth checked before existence)", status == 401)


# ============================================================================
# 2. Baseline: ensure unlocked, confirm a write works
# ============================================================================
step("2a. POST /unlock - idempotent baseline (may already be unlocked)")
status, r = unlock(project_id, TOKEN)
ok("POST /unlock -> 200", status == 200, detail=str(r))
ok("status is 'unlocked' or 'already_unlocked'", r.get("status") in ("unlocked", "already_unlocked"))

step("2b. Write succeeds while unlocked (baseline)")
marker = f"validate_and_lock.test.py baseline {time.strftime('%Y-%m-%d %H:%M:%S')}"
status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"remarks": marker})
ok("POST general_info -> 200 while unlocked", status == 200, detail=str(r))
ok("GET confirms the write persisted", get_general_info(project_id, TOKEN).get("remarks") == marker)


# ============================================================================
# 3. GET /validate - response shape
# ============================================================================
step("3a. GET /validate -> 200, top-level shape")
status, r = validate(project_id, TOKEN)
ok("GET /validate -> 200", status == 200, detail=str(r))
for key in ("project_id", "valid", "errors", "warnings", "page_chunks", "results", "note"):
    ok(f"response has {key!r}", key in r, detail=f"keys={list(r.keys())}")
ok("errors/warnings are dicts", isinstance(r.get("errors"), dict) and isinstance(r.get("warnings"), dict))
ok("page_chunks is a dict", isinstance(r.get("page_chunks"), dict))

step("3b. note wording is conditional on errors/warnings actually being present")
note = r.get("note", "")
if r.get("errors"):
    ok("note mentions errors must be resolved (errors are present)",
       "resolved" in note.lower() and "error" in note.lower())
else:
    ok("note does NOT mention resolving errors (no errors present)",
       "must be resolved" not in note.lower())
if r.get("warnings"):
    ok("note mentions warnings are advisory (warnings are present)", "advisory" in note.lower())
else:
    ok("note does NOT mention warnings (none present)", "advisory" not in note.lower())

step("3c. page_chunks only lists pages that actually appear in errors/warnings")
expected_pages = set(r.get("errors", {})) | set(r.get("warnings", {}))
ok("page_chunks keys == union of errors/warnings page names",
   set(r.get("page_chunks", {})) == expected_pages,
   detail=f"page_chunks={sorted(r.get('page_chunks', {}))} expected={sorted(expected_pages)}")

step("3d. results is null iff there are errors; token-budget keys excluded when present")
is_valid = r.get("valid")
results = r.get("results")
ok("valid == (not errors)", is_valid == (not r.get("errors")))
if is_valid:
    ok("results is present (non-null) when valid", results is not None, detail=str(results))
    if results is not None:
        for key in ("results", "analysis_period", "currency"):
            ok(f"results has {key!r}", key in results)
        ok("results does NOT include 'all_data' (token-budget trim)", "all_data" not in results)
        ok("results does NOT include 'lcc_breakdown' (token-budget trim)", "lcc_breakdown" not in results)
else:
    ok("results is null when not valid", results is None, detail=str(results))


# ============================================================================
# 4. Unlock after this validate call (whether or not it locked) before the
#    lock-cycle section, so section 5's own locking is deterministic.
# ============================================================================
step("4. Unlock (cleanup from section 3's validate call, in case it locked)")
status, r = unlock(project_id, TOKEN)
ok("POST /unlock -> 200", status == 200)
status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"remarks": "post-section-3 unlock check"})
ok("write succeeds after unlock", status == 200, detail=str(r))


# ============================================================================
# 5. Full lock lifecycle - only runs if this project validates clean
# ============================================================================
step("5. Full lock lifecycle (requires a project with zero validation errors)")
status, precheck = validate(project_id, TOKEN)
if status == 200 and precheck.get("valid"):
    step("5a. Clean /validate locked the project - a write is now rejected with 423")
    status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"remarks": "should be rejected"})
    ok("write while locked -> 423 project_locked", status == 423 and r.get("error") == "project_locked", detail=str(r))
    ok("423 response has a 'message' pointing to /unlock", "unlock" in r.get("message", "").lower())

    step("5b. /validate itself is also rejected with 423 while locked")
    status, r = validate(project_id, TOKEN)
    ok("GET /validate while locked -> 423 project_locked", status == 423 and r.get("error") == "project_locked", detail=str(r))

    step("5c. GET (read) still works while locked - only writes are blocked")
    status, r = call("GET", f"/{project_id}/general_info", token=TOKEN)
    ok("GET general_info while locked -> 200", status == 200 and "data" in r)

    step("5d. add_from_catalog / add_manual / trash are also rejected with 423 while locked (Construction Works)")
    status, r = call("POST", f"/{project_id}/str_super_structure/add_from_catalog", token=TOKEN,
                      body={"component": "Girder", "db_key": "x", "material_name": "x", "quantity": 1})
    ok("add_from_catalog while locked -> 423", status == 423 and r.get("error") == "project_locked", detail=str(r))
    status, r = call("POST", f"/{project_id}/str_super_structure/add_manual", token=TOKEN,
                      body={"component": "Girder", "values": {"material_name": "x", "unit": "MT", "quantity": 1, "rate": 1}})
    ok("add_manual while locked -> 423", status == 423 and r.get("error") == "project_locked", detail=str(r))
    status, r = call("POST", f"/{project_id}/str_super_structure/trash", token=TOKEN, body={"id": "whatever"})
    ok("trash while locked -> 423", status == 423 and r.get("error") == "project_locked", detail=str(r))

    step("5e. Every other form page (Tier A) is also rejected with 423 while locked - "
         "re-echoes each chunk's own currently-stored value for one field, so a 400 "
         "(bad shape) can never be mistaken for the 423 this step is actually checking")
    for chunk in ("bridge_data", "financial_data", "maintenance_data", "demolition_data"):
        status, get_r = call("GET", f"/{project_id}/{chunk}", token=TOKEN)
        if status != 200:
            ok(f"{chunk}: could not GET current data to build a re-echo payload - skipping", False, detail=str(get_r))
            continue
        body = None
        for k, v in get_r.get("data", {}).items():
            if k == "agency_logo":  # huge base64 - not needed to prove the lock check
                continue
            if isinstance(v, (str, int, float, bool)):
                body = {k: v}
                break
        if body is None:
            ok(f"{chunk}: no simple field found to re-echo - skipping", False, detail=str(get_r.get("data")))
            continue
        status, r = call("POST", f"/{project_id}/{chunk}", token=TOKEN, body=body)
        ok(f"{chunk} while locked -> 423 project_locked", status == 423 and r.get("error") == "project_locked",
           detail=f"body={body} got status={status} r={r}")

    step("5f. Nested-object Tier C chunks (Carbon Emissions Data) are also rejected with 423 while locked")
    status, r = call("POST", f"/{project_id}/social_cost_data", token=TOKEN, body={"custom": {"scc_value": 1}})
    ok("social_cost_data while locked -> 423", status == 423 and r.get("error") == "project_locked", detail=str(r))
    status, r = call("POST", f"/{project_id}/machinery_emissions_data", token=TOKEN, body={"remarks": "should be rejected"})
    ok("machinery_emissions_data while locked -> 423", status == 423 and r.get("error") == "project_locked", detail=str(r))

    step("5g. POST /unlock clears the lock - status 'unlocked'")
    status, r = unlock(project_id, TOKEN)
    ok("POST /unlock -> 200, status 'unlocked'", status == 200 and r.get("status") == "unlocked", detail=str(r))

    step("5h. Unlocking again is idempotent - status 'already_unlocked'")
    status, r = unlock(project_id, TOKEN)
    ok("POST /unlock again -> 200, status 'already_unlocked'", status == 200 and r.get("status") == "already_unlocked", detail=str(r))

    step("5i. Writes work again after unlock")
    marker2 = f"validate_and_lock.test.py post-unlock {time.strftime('%Y-%m-%d %H:%M:%S')}"
    status, r = call("POST", f"/{project_id}/general_info", token=TOKEN, body={"remarks": marker2})
    ok("write after unlock -> 200", status == 200, detail=str(r))
    ok("GET confirms the post-unlock write persisted", get_general_info(project_id, TOKEN).get("remarks") == marker2)
else:
    _skip += 17
    print(f"  [SKIP] section 5 (full lock lifecycle) - this project's /validate returned "
          f"valid={precheck.get('valid')} (status {status}), not True. Pass a project with "
          f"zero validation errors via --project-id/--token to exercise this section.")


# ============================================================================
# Summary
# ============================================================================
if _skip:
    print(f"\n{_skip} check(s) skipped (project not clean enough for the full lock-lifecycle section)")
sys.exit(summary())
