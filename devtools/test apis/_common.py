"""
devtools/test apis/_common.py

Shared HTTP/reporting/setup helpers for the standalone test files in this
folder (general_info.test.py, project_creation.test.py, and future
chunk-specific ones). NOT a test itself - no __main__ behaviour, and its
name deliberately doesn't end in .test.py so nothing mistakes it for one.

Each test file is its own independently-runnable script (`python
"whatever.test.py"`), so there's no single shared "main" to hook into -
instead, import what you need from here at the top of each file's own
top-level code:

    from _common import call, step, ok, build_arg_parser, setup_project_and_token, summary

    args = build_arg_parser(__doc__).parse_args()
    setup = setup_project_and_token(args)
    if setup is None:
        sys.exit(1)
    project_id, TOKEN = setup
    ... the file's own test steps, using call()/step()/ok() as before ...
    sys.exit(summary())

Each test file runs as its own separate `python ...` process, so the
module-level pass/fail counters below are never shared across files -
they only accumulate within whichever single script imported this module.
"""

import argparse
import http.client
import json
import time
import urllib.error
import urllib.request

BASE_URL = "http://127.0.0.1:8765"

_pass = 0
_fail = 0


def call(
    method: str,
    path: str,
    token: str | None = None,
    body: dict | list | None = None,
    timeout: float = 15.0,
):
    """Returns (status_code, parsed_json_body). Never raises on HTTP error
    status - the caller decides what's expected.

    `timeout` defaults to a generous 15s for ordinary calls, but callers that
    are about to trigger a modal GUI popup blocking on a human (e.g.
    /<project_id>/get_tokens) should pass a much larger value - the server
    itself waits up to ~120s for the user to click Allow/Deny, and a client
    timeout shorter than that would abandon the request while the dialog is
    still open.

    Not every error response is guaranteed to be JSON: a method this app's
    routes don't register for a given URL (e.g. DELETE) falls through to
    Werkzeug's own default error page, which is HTML, not one of this app's
    own jsonify()'d errors. Falls back to {"_non_json_body": True, "_raw":
    <snippet>} rather than letting json.loads() raise and crash the whole
    test run over a response shape a caller wasn't expecting."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{BASE_URL}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-API-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, http.client.InvalidURL) as e:
        return -1, {"_client_timeout": True, "_raw": str(e)}
    try:
        return status, json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return status, {"_non_json_body": True, "_raw": raw.decode("utf-8", errors="replace")[:200]}


def step(label: str) -> None:
    print(f"\n--- {label} ---")


def ok(label: str, condition: bool, detail: str = "") -> bool:
    global _pass, _fail
    if condition:
        _pass += 1
        print(f"  [PASS] {label}")
    else:
        _fail += 1
        print(f"  [FAIL] {label}" + (f"  ({detail})" if detail else ""))
    return condition


def summary() -> int:
    """Prints the final PASS/FAIL tally and returns the right process exit
    code (0 if everything passed, 1 otherwise) - call as `sys.exit(summary())`."""
    print(f"\n{'=' * 60}")
    print(f"RESULT: {_pass} passed, {_fail} failed")
    print(f"{'=' * 60}")
    return 1 if _fail else 0


def find_project(projects: list[dict], project_id: str) -> dict | None:
    return next((p for p in projects if p.get("project_id") == project_id), None)


def wait_until_open(project_id: str, label: str = "open", attempts: int = 5, delay: float = 3) -> bool:
    """Both POST /projects/open and POST /projects/new hand back control
    before the project is actually reachable - wait `delay` seconds, then
    poll GET /projects/active up to `attempts` times, `delay` apart."""
    print(f"  waiting {delay}s before polling ({label})...")
    time.sleep(delay)
    for attempt in range(1, attempts + 1):
        _, active = call("GET", "/projects/active")
        if find_project(active.get("projects", []), project_id):
            print(f"  confirmed open on attempt {attempt}/{attempts}")
            return True
        print(f"  attempt {attempt}/{attempts}: not open yet - retrying in {delay}s...")
        time.sleep(delay)
    return False


def build_arg_parser(doc: str | None = None) -> argparse.ArgumentParser:
    """Standard --project-id/--token flags every chunk-test file should
    expose, so a future orchestrator (all.test.py) can drive each one
    non-interactively after resolving both itself once."""
    description = doc.strip().splitlines()[0] if doc else ""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--project-id",
        help="use this already-known project non-interactively, instead of the numbered picker "
             "(e.g. one printed by project_creation.test.py)",
    )
    parser.add_argument(
        "--token",
        help="skip the interactive token prompt (e.g. when driven by all.test.py, which resolves "
             "the token once and passes it to every sub-test file)",
    )
    return parser


def ensure_project_open(project_id: str) -> bool:
    """Opens `project_id` if it isn't already active - skips the redundant
    POST /projects/open + ~3s poll entirely when GET /projects/active
    already lists it as open. The API itself treats re-opening an
    already-open project as a no-op (status: "already_open"), but there's
    no reason to pay the poll delay for something already known to be
    true."""
    status, active = call("GET", "/projects/active")
    if status == 200 and find_project(active.get("projects", []), project_id):
        print(f"  {project_id} is already open - skipping POST /projects/open")
        return True
    status, r = call("POST", "/projects/open", body={"project_id": project_id})
    if status != 200:
        print(f"  failed to open {project_id}: {r}")
        return False
    return wait_until_open(project_id, "open")


def _create_new_project_interactively() -> str | None:
    status, schema = call("GET", "/projects/new")
    if status != 200:
        print(f"  could not fetch /projects/new schema: {schema}")
        return None
    options = schema["fields"]["country"]["options"]
    preview = ", ".join(options[:10]) + (", ..." if len(options) > 10 else "")
    print(f"Countries (first 10 of {len(options)}): {preview}")
    try:
        country = input(f"Country (blank for {options[0]!r}): ").strip() or options[0]
        name = input("Project name (blank for a timestamped default): ").strip()
    except EOFError:
        country, name = options[0], ""
    name = name or f"test run {time.strftime('%Y-%m-%d %H:%M:%S')}"
    status, created = call("POST", "/projects/new", body={"project_name": name, "country": country})
    if status != 200:
        print(f"  failed to create project: {created}")
        return None
    print(f"  created: {created['project_id']}  (name={name!r}, country={country!r})")
    return created["project_id"]


def choose_project_interactively() -> str | None:
    """Lists every project on this machine, numbered, and asks the user to
    pick one - or 0 to create a new one instead. Returns the chosen
    project_id, or None if the user backs out (blank/invalid input)."""
    status, listing = call("GET", "/projects")
    projects = listing.get("projects", []) if status == 200 else []

    print("\nProjects on this machine:")
    print("  [0] Create a new project")
    for i, p in enumerate(projects, start=1):
        state = "open" if p.get("open") else p.get("status", "closed")
        print(f"  [{i}] {p.get('display_name')}  ({state})")

    try:
        choice = input("Choose a number (blank to cancel): ").strip()
    except EOFError:
        choice = ""
    if not choice:
        return None
    if choice == "0":
        return _create_new_project_interactively()
    try:
        idx = int(choice)
        if not (1 <= idx <= len(projects)):
            raise IndexError
        return projects[idx - 1]["project_id"]
    except (ValueError, IndexError):
        print("  invalid choice")
        return None


def get_token(project_id: str, cli_token: str | None) -> str:
    if cli_token:
        print("  using --token (skipping interactive prompt)")
        return cli_token
    print(f"In the app: File -> API Access -> copy the token for {project_id}.")
    try:
        return input("Paste token (blank to stop here): ").strip()
    except EOFError:
        return ""


def setup_project_and_token(args: argparse.Namespace) -> tuple[str, str] | None:
    """The common entry point every chunk-test file's own top-level code
    should call once, right after parsing --project-id/--token: resolves
    which project to use (the CLI flag if given, otherwise an interactive
    numbered picker - list projects, choose by number, or create new),
    makes sure it's open (skipping the redundant re-open call if it's
    already active), then resolves the token (the CLI flag if given,
    otherwise an interactive prompt). Returns (project_id, token), or None
    if the caller should stop (nothing chosen, open failed, or no token)."""
    project_id = args.project_id or choose_project_interactively()
    if not project_id:
        print("No project selected - stopping here.")
        return None
    if not ensure_project_open(project_id):
        print(f"Could not confirm {project_id!r} is open - stopping here.")
        return None
    token = get_token(project_id, args.token)
    if not token:
        print("\nNo token given - stopping.")
        return None
    return project_id, token
