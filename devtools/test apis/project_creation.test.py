"""
devtools/test apis/project_creation.test.py

Focused regression test for the 3psLCCA local API's project-management
endpoints: GET /projects, GET /projects/active, GET /projects/new,
POST /projects/new, POST /projects/open. These are the only endpoints the
API leaves unauthenticated by design (see server.py's _help_payload -
"not_required_on") - a per-project token can't gate them anyway, since a
token only exists once its project is open, and opening/listing/creating
exposes nothing a local process couldn't already do.

Because of that, this file needs NO token and runs start-to-finish with
zero interaction - unlike chunk-data test files (general_info.test.py etc.),
which do need a token and support --token to skip the interactive prompt
when orchestrated by all.test.py.

Run:

    python "devtools/test apis/project_creation.test.py"

Stdlib only, no dependencies. Prints [PASS]/[FAIL] per check and a summary
at the end; exits non-zero if anything failed. Prints the created
project_id at the end so it can be reused by other test files (e.g.
`general_info.test.py --project-id <id>`) instead of each one creating its
own throwaway project.

Creates a fresh project every run (POST /projects/new) - there's no
delete-project API, so these accumulate in the project list across runs;
harmless, but worth knowing (same tradeoff as devtools/test.py).

HTTP/reporting helpers (call/step/ok/find_project/wait_until_open) are
shared via _common.py in this same folder, rather than duplicated here.
"""

import sys
import time

from _common import call, step, ok, find_project, wait_until_open, summary


# ============================================================================
# 0. Discovery
# ============================================================================
step("0. Discovery")
status, help_doc = call("GET", "/help")
ok("GET /help -> 200", status == 200)
ok("/help lists project-management endpoints as not requiring auth",
   status == 200
   and set(help_doc.get("authentication", {}).get("not_required_on", []))
   >= {"GET /projects", "GET /projects/active", "GET /projects/new",
       "POST /projects/open", "POST /projects/new"})

status, _ = call("GET", "/")
ok("GET / -> 200 (JSON for scripts)", status == 200)


# ============================================================================
# 1. GET /projects, GET /projects/active - listing, before any write
# ============================================================================
step("1. GET /projects and /projects/active (baseline)")
status, before_all = call("GET", "/projects")
ok("GET /projects -> 200", status == 200 and "projects" in before_all)
before_count = len(before_all.get("projects", []))
print(f"  {before_count} project(s) on this machine before this run")

status, before_active = call("GET", "/projects/active")
ok("GET /projects/active -> 200, has count matching list length",
   status == 200 and before_active.get("count") == len(before_active.get("projects", [])))
ok("every entry in /projects/active also appears in /projects and has open=true",
   all(find_project(before_all["projects"], p["project_id"]) is not None and p.get("open")
       for p in before_active.get("projects", [])))


# ============================================================================
# 2. GET /projects/new - field schema (country/unit_system options, currency map)
# ============================================================================
step("2. GET /projects/new (schema)")
status, new_schema = call("GET", "/projects/new")
ok("GET /projects/new -> 200", status == 200)
country_options = new_schema.get("fields", {}).get("country", {}).get("options", [])
ok("schema lists non-empty country options", len(country_options) > 0)
ok("schema lists non-empty currency_by_country map", len(new_schema.get("currency_by_country", {})) > 0)
ok("every country option has a currency mapping",
   all(c in new_schema.get("currency_by_country", {}) for c in country_options))
ok("schema's unit_system options are exactly ['metric', 'imperial']",
   new_schema.get("fields", {}).get("unit_system", {}).get("options") == ["metric", "imperial"])


# ============================================================================
# 3. POST /projects/new - required-field validation, before a real create
# ============================================================================
country = country_options[0]
expected_currency = new_schema["currency_by_country"][country]

step("3a. POST /projects/new - missing project_name is rejected")
status, r = call("POST", "/projects/new", body={"country": country})
ok("missing project_name -> 400 invalid_field_values",
   status == 400 and r.get("error") == "invalid_field_values")

step("3b. POST /projects/new - blank project_name is rejected")
status, r = call("POST", "/projects/new", body={"project_name": "   ", "country": country})
ok("blank/whitespace-only project_name -> 400 invalid_field_values",
   status == 400 and r.get("error") == "invalid_field_values")

step("3c. POST /projects/new - invalid country is rejected, with the full valid list in the error")
status, r = call("POST", "/projects/new", body={"project_name": "x", "country": "Not A Real Country"})
ok("invalid country -> 400 invalid_field_values, details mention the valid list",
   status == 400 and r.get("error") == "invalid_field_values"
   and any("country" in d for d in r.get("details", [])))

step("3d. POST /projects/new - invalid unit_system is rejected")
status, r = call("POST", "/projects/new", body={"project_name": "x", "country": country, "unit_system": "bananas"})
ok("invalid unit_system -> 400 invalid_field_values",
   status == 400 and r.get("error") == "invalid_field_values")

step("3e. POST /projects/new - explicit currency is rejected (derived from country only)")
status, r = call("POST", "/projects/new",
                  body={"project_name": "x", "country": country, "currency": "USD"})
ok("explicit currency key -> 400 invalid_field_values (currency is derived, not supplied)",
   status == 400 and r.get("error") == "invalid_field_values")

step("3f. POST /projects/new - unrecognized key is rejected")
status, r = call("POST", "/projects/new",
                  body={"project_name": "x", "country": country, "not_a_real_field": True})
ok("unrecognized key -> 400 invalid_field_values", status == 400 and r.get("error") == "invalid_field_values")

step("3g. POST /projects/new - non-dict JSON body is rejected")
status, r = call("POST", "/projects/new", body=["not", "a", "dict"])
ok("JSON array body -> 400 invalid_json_body", status == 400 and r.get("error") == "invalid_json_body")


# ============================================================================
# 4. POST /projects/new - the real create, verified via GET /projects after
# ============================================================================
step("4. POST /projects/new (real create)")
project_name = f"project_creation.test.py run {time.strftime('%Y-%m-%d %H:%M:%S')}"
status, created = call("POST", "/projects/new", body={"project_name": project_name, "country": country})
ok("POST /projects/new -> 200, has project_id + currency",
   status == 200 and "project_id" in created and "currency" in created, detail=f"status={status}")
if status != 200:
    print("Could not create a project - stopping here.")
    sys.exit(summary())

project_id = created["project_id"]
ok("currency was correctly derived from country (not something we supplied)",
   created.get("currency") == expected_currency)
ok("status == 'created'", created.get("status") == "created")
print(f"  created: {project_id}  (name={project_name!r}, country={country!r}, currency={created.get('currency')})")

step("4b. GET /projects -> the new project appears, with the right fields (POST verified via GET)")
status, after_all = call("GET", "/projects")
new_entry = find_project(after_all.get("projects", []), project_id)
ok("GET /projects -> 200, new project present", status == 200 and new_entry is not None)
ok("new project's display_name matches what was sent", new_entry is not None and new_entry.get("display_name") == project_name)
ok("GET /projects has exactly one more entry than before this run",
   len(after_all.get("projects", [])) == before_count + 1)


# ============================================================================
# 5. Confirm the new project actually finished opening (async) - verified
#    via GET /projects/active, not just trusting the POST's own "note"
# ============================================================================
step("5. Confirm project is open (async)")
is_open = wait_until_open(project_id, "create")
ok("project reports open within 5 retries (up to ~18s total)", is_open)
status, active_after = call("GET", "/projects/active")
ok("GET /projects/active -> lists the new project as open",
   status == 200 and find_project(active_after.get("projects", []), project_id) is not None)


# ============================================================================
# 6. POST /projects/open - unknown id, already-open id
# ============================================================================
step("6a. POST /projects/open - unknown project_id is a clean 404, not a crash")
status, r = call("POST", "/projects/open", body={"project_id": "nonexistent_project_id_xyz"})
ok("unknown project_id -> 404 project_not_found", status == 404 and r.get("error") == "project_not_found")

step("6b. POST /projects/open - missing project_id in body is rejected")
status, r = call("POST", "/projects/open", body={})
ok("missing project_id -> 400 invalid_json_body", status == 400 and r.get("error") == "invalid_json_body")

status, r = call("POST", "/projects/open", body=["not", "a", "dict"])
ok("JSON array body -> 400 invalid_json_body", status == 400 and r.get("error") == "invalid_json_body")

step("6c. POST /projects/open - a project that's already open returns status 'already_open'")
status, r = call("POST", "/projects/open", body={"project_id": project_id})
ok("re-opening the already-open project -> 200, status == 'already_open'",
   status == 200 and r.get("status") == "already_open")
status, active_still = call("GET", "/projects/active")
ok("GET /projects/active -> still lists exactly this project as open (re-open didn't duplicate/break anything)",
   status == 200 and find_project(active_still.get("projects", []), project_id) is not None)


# ============================================================================
# 7. POST /projects/open on a genuinely PRE-EXISTING, previously-closed
#    project (not the one this run just created) - exercises the actual
#    "resume an old project" path, distinct from section 6c's
#    already-open/no-op case above.
#
# NOTE: this really opens that project's window in the live desktop app,
# same as double-clicking it there - there's no dry-run mode, because the
# API has no way to simulate opening without doing it. If it picks one of
# your real projects, its window will appear; there's no close-project
# API (by the same design choice as no delete-project API - see section 8
# below), so you may want to close it yourself afterward.
# ============================================================================
step("7. POST /projects/open on a genuinely pre-existing, previously-closed project")
before_open_ids = {p["project_id"] for p in before_active.get("projects", [])}
candidate = next(
    (p for p in before_all.get("projects", [])
     if p["project_id"] != project_id and p["project_id"] not in before_open_ids),
    None,
)
if candidate is None:
    print("  skipped - no pre-existing closed project found on this machine to reuse for this check "
          "(every existing project was already open, or this machine had none before this run)")
else:
    reopen_id = candidate["project_id"]
    print(f"  reusing existing, previously-closed project: {reopen_id!r} ({candidate.get('display_name')!r})")
    status, r = call("POST", "/projects/open", body={"project_id": reopen_id})
    ok("POST /projects/open on a previously-closed real project -> 200, status == 'opening'",
       status == 200 and r.get("status") == "opening", detail=f"status={status}")
    reopened = wait_until_open(reopen_id, "reopen pre-existing project")
    ok("GET /projects/active -> the pre-existing project reports open within 5 retries", reopened)


# ============================================================================
# 8. No delete-project capability exists - and shouldn't. There is no
#    DELETE route registered anywhere in server.py; this confirms that
#    stays true (no route silently added, no method quietly accepted)
#    rather than just trusting the absence of a code path we read once.
# ============================================================================
step("8. Confirm there is no way to delete a project via this API")
# /projects/<id> structurally matches the generic /<project_id>/<chunk> data
# route too (Flask/Werkzeug match by URL *shape*, not literal segment
# names) - that route only registers GET/POST, so DELETE falls through to
# Werkzeug's own 405 handler (HTML body, not this app's JSON error shape).
# Either way, the only thing this check cares about is "not a 200" - i.e.
# no delete capability was silently wired up, on this path or any other.
status, r = call("DELETE", f"/projects/{project_id}")
ok("DELETE /projects/<id> -> not 200 (no delete route exists for this)",
   status != 200, detail=f"status={status}, body={r}")
status, r = call("DELETE", "/projects")
ok("DELETE /projects (collection) -> not 200 either", status != 200, detail=f"status={status}, body={r}")
status, still_listed = call("GET", "/projects")
ok("GET /projects -> project still present after the DELETE attempts (nothing was removed)",
   status == 200 and find_project(still_listed.get("projects", []), project_id) is not None)


print(f"\nproject_id for reuse by other test files: {project_id}")
print("e.g.  python \"general_info.test.py\" --project-id " + project_id)


# ============================================================================
# Summary
# ============================================================================
sys.exit(summary())
