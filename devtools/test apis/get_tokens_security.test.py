"""
devtools/test apis/get_tokens_security.test.py

Fully automated security/fuzzing regression test for
/<project_id>/get_tokens. Zero interaction, zero GUI popups - safe to run
unattended or wire into CI against a running GUI instance.

Why this never triggers a popup:
  - Every project_id used here is either nonexistent/unopened (bridge.py's
    _get_tokens returns "project_not_open" before it ever looks at consent
    state or builds a dialog) or a fresh throwaway project this file creates
    and never calls GET/POST .../get_tokens against with a real chance of
    reaching UNSET-triggers-a-dialog territory (the forged-token checks hit
    a *different*, already-existing protected endpoint, not get_tokens).

Covers:
  1. Discovery / server reachability
  2. GET and POST both routed, 404 project_not_open for unknown/closed ids
  3. Path traversal, XSS, SQLi-style, null-byte, and oversized project_id
     payloads - all handled safely (400/404), never a 500
  4. HTTP method fuzzing: PUT/DELETE/PATCH -> 405; HEAD behaves like GET
     (Flask auto-registers HEAD for any GET route - it must NOT 405)
  5. Token forgery / auth bypass against a real protected endpoint
  6. Flooding a never-opened project never produces anything but 404 -
     there is deliberately NO IP/global rate limiter in the current design
     (the only anti-flood mechanism is the per-OPEN-project 3-prompt cap in
     tokens.py, which only ever engages once a real popup has been shown -
     see get_tokens_consent.test.py for that half, which needs a human).

Run:
    python "devtools/test apis/get_tokens_security.test.py"
"""

import sys

from _common import call, step, ok, summary

FAKE_PROJECT = "fake_non_existent_project_99999"


# ============================================================================
# 0. Discovery
# ============================================================================
step("0. Server Connection & Discovery")
status, active_res = call("GET", "/projects/active")
if status != 200:
    print("ERROR: Could not connect to API server at http://127.0.0.1:8765.")
    print("       Please start the 3psLCCA GUI application first.")
    sys.exit(1)
print("  server reachable")


# ============================================================================
# 1. GET & POST routing, unknown/closed project isolation
# ============================================================================
step("1. GET & POST /<project_id>/get_tokens - unknown project")
for method in ("GET", "POST"):
    status, r = call(method, f"/{FAKE_PROJECT}/get_tokens")
    ok(f"{method} /{FAKE_PROJECT}/get_tokens -> 404 project_not_open",
       status == 404 and r.get("error") == "project_not_open")


# ============================================================================
# 2. Malicious / malformed project_id payloads
# ============================================================================
step("2. Path Traversal, Injection & Malformed project_id")

malicious_ids = [
    ("../../get_tokens", "path traversal (raw)"),
    ("..%2F..%2Fget_tokens", "path traversal (encoded slashes)"),
    ("%3Cscript%3Ealert(1)%3C%2Fscript%3E", "XSS payload"),
    ("' OR '1'='1", "SQL injection style"),
    ("%00", "null byte"),
    ("A" * 5000, "oversized project_id (5000 chars)"),
    ("..", "bare dotdot segment"),
    ("%2e%2e%2f%2e%2e%2fetc%2fpasswd", "encoded traversal to /etc/passwd"),
]
from urllib.parse import quote

for raw_id, label in malicious_ids:
    status, r = call("GET", f"/{quote(raw_id, safe='')}/get_tokens")
    ok(f"GET /{label} -> safely rejected (400/404, never 500)",
       status in (400, 404),
       detail=f"got {status}")

status, r = call("GET", "//get_tokens")
ok("GET //get_tokens (empty project_id segment) -> 404 (route/collapse mismatch)",
   status == 404)


# ============================================================================
# 3. HTTP method fuzzing
# ============================================================================
step("3. HTTP Method Fuzzing")
for method in ["PUT", "DELETE", "PATCH"]:
    status, r = call(method, f"/{FAKE_PROJECT}/get_tokens")
    ok(f"{method} /{FAKE_PROJECT}/get_tokens -> 405 Method Not Allowed",
       status == 405)

# HEAD is auto-registered by Flask for any GET route - must behave like GET
# (i.e. still resolve project lookup), never 405.
status, r = call("HEAD", f"/{FAKE_PROJECT}/get_tokens")
ok("HEAD /<project_id>/get_tokens -> NOT 405 (Flask auto-provides HEAD for GET)",
   status != 405, detail=f"got {status}")


# ============================================================================
# 4. Token forgery / auth bypass against a real protected endpoint
# ============================================================================
step("4. Token Forgery & Auth Bypass Checks")
active_projects = active_res.get("projects", [])
if not active_projects:
    print("  (skipped: no projects currently open in the GUI - open one to "
          "exercise this section)")
else:
    target_project_id = active_projects[0]["project_id"]
    target_name = active_projects[0].get("display_name", target_project_id)
    print(f"  targeting: {target_name} ({target_project_id})")
    forged_tokens = [
        "invalid_token_123",
        "",
        "' OR '1'='1",
        "null",
        "undefined",
        "A" * 500,
        "..%2f..%2f",
        "<script>alert(1)</script>",
    ]
    for bad_token in forged_tokens:
        status, r = call("GET", f"/{target_project_id}/general_info", token=bad_token)
        ok(f"Auth bypass attempt with token '{bad_token[:15]}...' -> 401 Unauthorized",
           status == 401 and r.get("error") == "unauthorized")

    status, r = call("GET", f"/{target_project_id}/general_info")
    ok("No token at all -> 401 Unauthorized",
       status == 401 and r.get("error") == "unauthorized")


# ============================================================================
# 5. Flooding a never-opened project - must stay 404, never 429/500
# ============================================================================
step("5. Flood a Never-Opened Project (no global rate limiter by design)")
# bridge.py's _get_tokens checks _find_window() FIRST, before it ever looks
# at tokens.is_delivered()/can_prompt() - so a project that was never opened
# can never reach the 3-prompt cap (that's per-OPEN-project state) and can
# never trigger a popup. Hammering it should just be 404, every single time,
# with no accidental throttling regression and no risk of a popup appearing.
flood_project = "flood_probe_never_opened_project"
results = []
for _ in range(20):
    status, r = call("GET", f"/{flood_project}/get_tokens")
    results.append((status, r.get("error")))
all_404 = all(status == 404 and err == "project_not_open" for status, err in results)
ok("20 rapid requests to a never-opened project -> always 404 project_not_open, "
   "never 429/500/anything else",
   all_404, detail=str(results))


sys.exit(summary())
