"""
devtools/test apis/get_tokens_consent.test.py

Interactive regression test for the human-in-the-loop side of
/<project_id>/get_tokens under the current (simplified) design:

  - No persisted session status (no UNSET/ALLOWED/DENIED tri-state). Every
    call either finds the token already delivered, hits this project's
    3-prompt cap, or shows a fresh Allow/Deny popup - Deny does NOT stick,
    the next call just asks again.
  - One-time delivery: once handed out over HTTP, never sent again
    automatically - the only way to get it again is File -> API Access.
  - A 3-popup cap per project per session (tokens.MAX_PROMPTS): the 4th
    ask in a row (with no Allow in between) is rejected outright, no popup.
  - File -> API Access is the plain original dialog again: Generate /
    Regenerate / Revoke Token - no "Allow app to communicate" wording.
  - Revoke Token fully resets a project's API-access state (token, the
    one-time-delivery flag, AND the prompt-cap counter) - it's a full
    reset, not just "block requests".
  - No thread-leader synchronization any more: two simultaneous requests
    for the same project may each independently raise their own popup.
    This file documents that rather than asserting mutual exclusion.

Because all of this state is keyed by project_id (not global/session-wide),
a fresh throwaway project starts clean regardless of how long the app has
been running - blocks below do NOT need to restart the whole app between
each other. Only make sure the app running right now has actually loaded
the current source (see the reminder at the very start).

All user-facing prompts show "<project name> (<project_id>)" rather than a
bare id, so you can actually recognize which window to look at.

Run:
    python "devtools/test apis/get_tokens_consent.test.py"
"""

import sys
import threading
import time

from _common import call, step, ok, summary

# get_tokens can block on a modal GUI dialog waiting for a human, so give
# it a lot more slack than the default HTTP timeout.
POPUP_TIMEOUT = 150.0
# Response-time ceiling used to assert "no popup was shown" - an
# already-delivered or already-capped project resolves in milliseconds;
# a genuine popup wait would take seconds-to-minutes.
NO_POPUP_CEILING = 5.0


def display(name: str, project_id: str) -> str:
    """"<project name> (<project_id>)" - the display convention used in
    every user-facing prompt below, so a human reads the name they
    recognize instead of a bare internal id."""
    return f"{name} ({project_id})"


def create_fresh_project(label: str) -> tuple[str, str] | None:
    """Returns (project_id, display_name), or None on failure."""
    status, schema = call("GET", "/projects/new")
    if status != 200:
        print(f"  could not fetch /projects/new schema: {schema}")
        return None
    country = schema["fields"]["country"]["options"][0]
    name = f"get_tokens consent test - {label} - {time.strftime('%H:%M:%S')}"
    status, created = call("POST", "/projects/new", body={"project_name": name, "country": country})
    if status != 200:
        print(f"  failed to create project ({label}): {created}")
        return None
    pid = created["project_id"]
    print(f"  created {display(name, pid)}")
    return pid, name


def press_enter(prompt: str) -> None:
    try:
        input(f"\n[ACTION REQUIRED] {prompt}\nPress Enter once done... ")
    except EOFError:
        pass


def ask_yes(prompt: str) -> bool:
    try:
        return input(f"\n[CONFIRM] {prompt} (y/n): ").strip().lower().startswith("y")
    except EOFError:
        return False


def announce_project(label: str) -> None:
    """A separate gate right after creation, before anything tries to
    trigger a popup for it: gives the user a moment to switch to the GUI
    and actually find/confirm the new project window before the request
    that raises the dialog is sent."""
    press_enter(
        f"Project {label} has been created. Switch to the 3psLCCA GUI and "
        "confirm its window is visible, then press Enter here."
    )


def trigger_popup_and_wait(project_id: str, ready_prompt: str, timeout: float = POPUP_TIMEOUT):
    """For any call expected to raise the Allow/Deny popup: asks the user
    to confirm they're ready FIRST, only THEN sends the request that
    actually shows the dialog, and never prompts a second time after that -
    the real "click" happens in the GUI itself, so this just blocks on the
    HTTP response until that happens. Returns (status, body)."""
    press_enter(ready_prompt)

    result: dict = {}

    def _do():
        result["status"], result["body"] = call("GET", f"/{project_id}/get_tokens", timeout=timeout)

    t = threading.Thread(target=_do)
    t.start()
    print("  request sent - waiting for your response to the popup in the GUI...")
    t.join(timeout=timeout + 10)
    if t.is_alive():
        print("  WARNING: request still hasn't returned - the popup may still be open, or the app may be stuck.")
        t.join(timeout=30)
    return result.get("status"), result.get("body", {})


def wait_for_server(retries: int = 30, delay: float = 2.0) -> bool:
    for _ in range(retries):
        status, _ = call("GET", "/projects/active", timeout=3.0)
        if status == 200:
            return True
        time.sleep(delay)
    return False


step("0. Server Connection Check")
press_enter(
    "Make sure the 3psLCCA GUI you're about to test is a FRESH launch - "
    "fully quit and relaunch it now if it's been running since before the "
    "last code change. Python does not hot-reload source files into an "
    "already-running process, so testing against a stale process will "
    "silently re-run whatever bug the last fix was for."
)
status, _ = call("GET", "/projects/active")
if status != 200:
    print("ERROR: Could not connect to API server at http://127.0.0.1:8765.")
    print("       Please start the 3psLCCA GUI application first.")
    sys.exit(1)
print("  server reachable")


# ============================================================================
# BLOCK 1 - One-time delivery: Allow, then locked out automatically
# ============================================================================
step("BLOCK 1 - One-Time Delivery (Allow Flow)")
result = create_fresh_project("allow-flow")
if not result:
    print("Could not create the allow-flow project - stopping here.")
    sys.exit(1)
project_allow, name_allow = result
label_allow = display(name_allow, project_allow)
announce_project(label_allow)

step("1. First-Time Access Request & Allow")
t0 = time.monotonic()
status, r = trigger_popup_and_wait(
    project_allow,
    f"Press Enter to send the request for {label_allow} - a popup titled "
    "'API Access Request' will then appear; click ALLOW on it.",
)
elapsed = time.monotonic() - t0
ok("GET /get_tokens -> 200 OK on user Allow", status == 200, detail=f"got {status} {r}")
token_allow = r.get("token")
ok("Token delivered on initial consent", bool(token_allow))
print(f"  (took {elapsed:.1f}s)")

step("2. Anti-Token-Theft (One-Time Delivery Enforcement)")
t0 = time.monotonic()
status, r = call("GET", f"/{project_allow}/get_tokens")
elapsed = time.monotonic() - t0
ok("Second GET /get_tokens -> 403 token_already_delivered, instantly (no popup)",
   status == 403 and r.get("error") == "token_already_delivered" and elapsed < NO_POPUP_CEILING,
   detail=f"status={status} took={elapsed:.1f}s body={r}")

status, r = call("POST", f"/{project_allow}/get_tokens")
ok("POST /get_tokens also blocked after delivery -> 403 token_already_delivered",
   status == 403 and r.get("error") == "token_already_delivered")

step("3. Delivered Token Grants Real API Access")
status, r = call("GET", f"/{project_allow}/general_info", token=token_allow)
ok("GET /general_info with delivered token -> 200 OK", status == 200)
ok("Response contains project data", "data" in r)

status, r = call("GET", f"/{project_allow}/general_info", token="garbage_token_xyz")
ok("GET /general_info with a wrong token -> 401 Unauthorized (delivery didn't loosen auth)",
   status == 401 and r.get("error") == "unauthorized")


# ============================================================================
# BLOCK 2 - Deny does NOT persist, and the 3-prompt cap
# ============================================================================
step("BLOCK 2 - Deny Is Non-Sticky, Then the 3-Prompt Cap")
result = create_fresh_project("deny-flow")
if not result:
    print("Could not create the deny-flow project - stopping here.")
    sys.exit(1)
project_deny, name_deny = result
label_deny = display(name_deny, project_deny)
announce_project(label_deny)

step("4. Deny Three Times In A Row - Each One Re-Prompts")
for i in range(1, 4):
    status, r = trigger_popup_and_wait(
        project_deny,
        f"Press Enter to send request #{i} of 3 for {label_deny} - an "
        "'API Access Request' popup will appear each time (Deny doesn't "
        "stick); click DENY (or close it with the X).",
    )
    ok(f"Deny attempt #{i}/3 -> 403 denied, popup shown fresh each time",
       status == 403 and r.get("error") == "denied",
       detail=f"got {status} {r}")

step("5. Fourth Attempt - Popup Cap Reached, No More Popups")
t0 = time.monotonic()
status, r = call("GET", f"/{project_deny}/get_tokens")
elapsed = time.monotonic() - t0
ok("4th GET /get_tokens -> 429 too_many_requests, instantly, no popup",
   status == 429 and r.get("error") == "too_many_requests" and elapsed < NO_POPUP_CEILING,
   detail=f"status={status} took={elapsed:.1f}s body={r}")

status, r = call("GET", f"/{project_deny}/get_tokens")
ok("Cap stays hit on further calls too (not a one-shot fluke)",
   status == 429 and r.get("error") == "too_many_requests")


# ============================================================================
# BLOCK 3 - File -> API Access (Generate/Regenerate/Revoke) interplay
# ============================================================================
step("BLOCK 3 - File -> API Access: Generate, Revoke, Regenerate")
result = create_fresh_project("manual-dialog")
if not result:
    print("Could not create the manual-dialog project - stopping here.")
    sys.exit(1)
project_manual, name_manual = result
label_manual = display(name_manual, project_manual)
announce_project(label_manual)

step("6. Generate Token via GUI Does NOT Bypass the HTTP Handshake")
press_enter(
    f"In the 3psLCCA GUI, switch to the {label_manual} project window, "
    "click File -> API Access, then click 'Generate Token'. Leave the "
    "dialog open so you can copy the token shown."
)
try:
    gui_token_1 = input("Paste the token shown in the dialog: ").strip()
except EOFError:
    gui_token_1 = ""

status, r = trigger_popup_and_wait(
    project_manual,
    "Generating a token via the GUI does NOT mark it delivered over HTTP - "
    "press Enter to send the request; a popup will still appear. Click ALLOW.",
)
ok("GET /get_tokens still shows a popup even though a token already existed "
   "from Generate Token, and returns 200 on Allow",
   status == 200, detail=f"got {status} {r}")
if gui_token_1:
    ok("Token delivered over HTTP matches the one Generate Token showed in the GUI "
       "(ensure_token reuses the existing token rather than making a new one)",
       r.get("token") == gui_token_1)
else:
    print("  (skipped comparison - no token pasted)")

status, r = call("GET", f"/{project_manual}/get_tokens")
ok("Next GET /get_tokens -> 403 token_already_delivered",
   status == 403 and r.get("error") == "token_already_delivered")

step("7. Revoke Token Fully Resets This Project's State")
press_enter(
    f"In the {label_manual} project's File -> API Access dialog, "
    "click 'Revoke Token', then close the dialog."
)
status, r = trigger_popup_and_wait(
    project_manual,
    "Revoke Token resets everything for this project (token, delivery "
    "flag, AND the prompt cap) - press Enter to send the request; a fresh "
    "popup should appear as if this project had never been asked before. "
    "Click ALLOW.",
)
ok("GET /get_tokens after Revoke -> fresh popup, 200 OK on Allow "
   "(proves Revoke resets delivery state, not just the token value)",
   status == 200, detail=f"got {status} {r}")
token_after_revoke = r.get("token")
if gui_token_1 and token_after_revoke:
    ok("Token issued after Revoke is DIFFERENT from the pre-revoke token",
       token_after_revoke != gui_token_1)

step("8. Regenerate Token Re-Arms One-Time Delivery")
press_enter(
    f"In the {label_manual} project's File -> API Access dialog, "
    "click 'Regenerate Token'. Leave the dialog open so you can copy the "
    "new token shown."
)
try:
    gui_token_2 = input("Paste the newly regenerated token: ").strip()
except EOFError:
    gui_token_2 = ""

status, r = trigger_popup_and_wait(
    project_manual,
    "Regenerate Token re-arms one-time delivery, so a popup will appear "
    "again - press Enter to send the request. Click ALLOW.",
)
ok("GET /get_tokens after Regenerate -> 200 OK (delivery flag was re-armed)",
   status == 200, detail=f"got {status} {r}")
if gui_token_2:
    ok("Token delivered over HTTP matches the regenerated token shown in the GUI",
       r.get("token") == gui_token_2)
else:
    print("  (skipped comparison - no token pasted)")


# ============================================================================
# BLOCK 4 - Window close clears token + delivery + prompt-cap state
# ============================================================================
step("BLOCK 4 - Window Close / Reopen Cleanup")
result = create_fresh_project("window-close")
if not result:
    print("Could not create the window-close project - stopping here.")
    sys.exit(1)
project_close, name_close = result
label_close = display(name_close, project_close)
announce_project(label_close)

step("9. Session Cleanup on Project Window Close")
status, r = trigger_popup_and_wait(
    project_close,
    f"Press Enter to send the request for {label_close} - an 'API Access "
    "Request' popup will then appear; click ALLOW.",
)
ok("Initial Allow succeeds -> 200 OK", status == 200, detail=f"got {status} {r}")

press_enter(
    f"Close the {label_close} project's window in the 3psLCCA GUI "
    "(File -> Close, or the window's close button) - but do NOT quit the "
    "whole app."
)
status, r = call("GET", f"/{project_close}/get_tokens")
ok("GET /get_tokens on a closed project -> 404 project_not_open",
   status == 404 and r.get("error") == "project_not_open")

press_enter(
    f"Reopen {label_close} (e.g. from the app's home screen), "
    "and wait for it to finish loading."
)
status, active = call("GET", "/projects/active")
reopened = status == 200 and any(p.get("project_id") == project_close for p in active.get("projects", []))
if not reopened:
    print("  (could not confirm reopen via /projects/active - continuing anyway)")

t0 = time.monotonic()
status, r = trigger_popup_and_wait(
    project_close,
    "Press Enter to send the request - a fresh 'API Access Request' "
    "popup should appear (closing wiped this project's prior "
    "delivered/prompt-count state). Click ALLOW.",
)
elapsed = time.monotonic() - t0
ok("Reopened project shows a fresh popup and re-Allow succeeds -> 200 OK "
   "(proves close cleared prior delivered/prompt-cap state, not just reused it)",
   status == 200, detail=f"status={status} took={elapsed:.1f}s")


# ============================================================================
# BLOCK 5 - Concurrency: no synchronization guarantee any more
# ============================================================================
step("BLOCK 5 - Concurrency (No Thread-Leader Guard)")
result = create_fresh_project("concurrency")
if not result:
    print("Could not create the concurrency project - stopping here.")
    sys.exit(1)
project_concurrency, name_concurrency = result
label_concurrency = display(name_concurrency, project_concurrency)
announce_project(label_concurrency)

step("10. Two Simultaneous Requests - Document the Actual Behavior")
press_enter(
    f"Press Enter to fire two simultaneous GET /get_tokens requests for "
    f"{label_concurrency}. There is NO synchronization in the current "
    "design, so you may see ONE popup or TWO - either is expected. Click "
    "ALLOW on whichever popup(s) appear."
)

results = {}


def _fire(tag):
    status, r = call("GET", f"/{project_concurrency}/get_tokens", timeout=POPUP_TIMEOUT)
    results[tag] = (status, r)


t1 = threading.Thread(target=_fire, args=("A",))
t2 = threading.Thread(target=_fire, args=("B",))
t1.start()
time.sleep(0.05)
t2.start()
print("  requests sent - waiting for your response(s) to the popup(s) in the GUI...")

t1.join(timeout=POPUP_TIMEOUT + 10)
t2.join(timeout=POPUP_TIMEOUT + 10)

ok("Both concurrent requests returned (no thread hung / GUI never froze)",
   "A" in results and "B" in results,
   detail=str(results))

statuses = [results.get("A", (None, None))[0], results.get("B", (None, None))[0]]
tokens_seen = [results.get(k, (None, {}))[1].get("token") for k in ("A", "B")]
successes = [s for s in statuses if s == 200]

if len(successes) == 2:
    print("  Both requests were Allowed - since ensure_token() is idempotent, "
          "both should have received the SAME token value.")
    ok("Both concurrent Allows returned the identical token (idempotent ensure_token)",
       tokens_seen[0] == tokens_seen[1] and tokens_seen[0] is not None,
       detail=f"tokens={tokens_seen}")
elif len(successes) == 1:
    ok("Exactly one request was Allowed; the other was cleanly rejected "
       "(403/429), not left hanging or errored",
       any(s in (403, 429) for s in statuses if s != 200),
       detail=f"statuses={statuses}")
else:
    print(f"  Neither request succeeded (statuses={statuses}) - fine if both were denied.")

saw_popups = ask_yes("Did you see one or two popups (i.e. it behaved sensibly, "
                      "not zero and not a crash)?")
ok("Human-confirmed: the app handled two simultaneous requests without "
   "crashing or freezing",
   saw_popups)


sys.exit(summary())
