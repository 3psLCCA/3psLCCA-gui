"""
devtools/test apis/cross_site_block.test.py

Brutal test for the "no requests from web pages" guard in server.py
(_create_app's before_request hook). Throws every browser-reachable trick
we could think of at every kind of route, plus a pile of header garbage a
browser could never send, and checks that:

  - anything that looks like it came from another web page is refused
    with 403 (cross_site_request_blocked / host_not_allowed) BEFORE the
    route runs - so no popup, no project created, nothing opened;
  - scripts, curl, the address bar and the API's own help page still work;
  - DNS rebinding (evil.com resolving to 127.0.0.1, so the browser treats
    the page as same-origin and could READ replies) is refused by Host;
  - no response ever carries Access-Control-Allow-Origin;
  - nothing ever 500s, and a flood of blocked requests doesn't wedge the
    server.

Uses raw http.client so every header (Host, duplicate Origins, odd
casing, oversized values) is under the test's control - urllib would
"helpfully" rewrite some of them.

Never triggers a GUI popup: every request that targets get_tokens uses a
project id that doesn't exist, so even if the guard leaked, the route
would answer 404 project_not_open before any dialog could be built.
POST /projects/new is only ever sent an empty body, so a leak gives 400
instead of creating a project.

Run against the running GUI (needs the app restarted on the new code):
    python "devtools/test apis/cross_site_block.test.py"

Run against the current source with no GUI at all (starts server.py's
Flask app on a spare port with a stub bridge):
    python "devtools/test apis/cross_site_block.test.py" --self-host
"""

import argparse
import http.client
import json
import socket
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from _common import step, ok, summary

FAKE = "fake_cross_site_probe_project"

parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
parser.add_argument("--self-host", action="store_true",
                    help="start server.py's app from source on a spare port (stub bridge, no GUI)")
args = parser.parse_args()

HOST, PORT = "127.0.0.1", 8765

if args.self_host:
    import logging
    import os
    logging.getLogger("werkzeug").setLevel(logging.ERROR)  # no per-request access log
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
    from werkzeug.serving import make_server
    from three_ps_lcca_gui.gui.api.server import _create_app

    class _StubBridge:
        """Answers like a GUI with zero open projects."""
        def call(self, name, *a, **kw):
            if name == "list_projects":
                return {"projects": []}
            return {"error": "project_not_open", "message": "stub"}

    with socket.socket() as s:
        s.bind((HOST, 0))
        PORT = s.getsockname()[1]
    _httpd = make_server(HOST, PORT, _create_app(_StubBridge()), threaded=True)
    threading.Thread(target=_httpd.serve_forever, daemon=True).start()
    print(f"  self-hosted current server.py on {HOST}:{PORT}")

SELF = f"http://{HOST}:{PORT}"


def raw(method, path, headers=(), body=None, host=None, timeout=10.0):
    """headers: list of (name, value) - duplicates allowed, order kept.
    host: Host header value; None = the real one; "" = send no Host at all.
    Returns (status, json_or_None, header_dict_lowercased)."""
    conn = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
    try:
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        if host is None:
            conn.putheader("Host", f"{HOST}:{PORT}")
        elif host != "":
            conn.putheader("Host", host)
        data = None
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Content-Length", str(len(data)))
        for k, v in headers:
            conn.putheader(k, v)
        conn.endheaders(data)
        resp = conn.getresponse()
        rawbody = resp.read()
        hdrs = {k.lower(): v for k, v in resp.getheaders()}
        try:
            parsed = json.loads(rawbody.decode("utf-8"))
        except Exception:
            parsed = None
        return resp.status, parsed, hdrs
    except (OSError, http.client.HTTPException) as e:
        return -1, {"_conn_error": str(e)}, {}
    finally:
        conn.close()


BLOCK_ERRORS = ("cross_site_request_blocked", "host_not_allowed")


def is_blocked(status, body):
    return status == 403 and isinstance(body, dict) and body.get("error") in BLOCK_ERRORS


# Every kind of route: unauthenticated app routes, get_tokens (both
# methods), a project data route, unknown routes (404) and a method the
# route doesn't allow (405). The guard must run before routing outcomes.
TARGETS = [
    ("GET", "/", None),
    ("GET", "/help", None),
    ("GET", "/projects", None),
    ("GET", "/projects/active", None),
    ("GET", "/projects/new", None),
    ("POST", "/projects/new", {}),
    ("POST", "/projects/open", {"project_id": FAKE}),
    ("GET", f"/{FAKE}/get_tokens", None),
    ("POST", f"/{FAKE}/get_tokens", None),
    ("HEAD", f"/{FAKE}/get_tokens", None),
    ("GET", f"/{FAKE}/general_info", None),
    ("POST", f"/{FAKE}/general_info", {"x": 1}),
    ("POST", f"/{FAKE}/unlock", None),
    ("GET", "/no/such/route/at/all", None),
    ("PUT", f"/{FAKE}/get_tokens", None),
    ("DELETE", f"/{FAKE}/get_tokens", None),
    ("OPTIONS", f"/{FAKE}/get_tokens", None),
    ("OPTIONS", "/projects/new", None),
]


def blocked_everywhere(label, headers=(), host=None):
    fails = []
    for method, path, body in TARGETS:
        status, r, h = raw(method, path, headers, body, host=host)
        # HEAD has no body to inspect - status alone has to do.
        good = status == 403 if method == "HEAD" else is_blocked(status, r)
        if not good:
            fails.append(f"{method} {path} -> {status} {(r or {}).get('error')}")
    ok(f"{label}: blocked on all {len(TARGETS)} routes", not fails,
       detail="; ".join(fails[:4]) + (f" (+{len(fails) - 4} more)" if len(fails) > 4 else ""))


def allowed(label, headers=(), host=None, path="/projects/active"):
    status, r, _ = raw("GET", path, headers, host=host)
    ok(f"{label}: allowed (200)", status == 200,
       detail=f"got {status} {(r or {}).get('error')}")


# ============================================================================
step("0. Server reachable and running the guard")
status, _, _ = raw("GET", "/projects/active")
if status != 200:
    print(f"ERROR: no API server at {SELF} (got {status}). Start the app, or use --self-host.")
    sys.exit(1)
status, r, _ = raw("GET", "/projects/active", [("Sec-Fetch-Site", "cross-site")])
if not is_blocked(status, r):
    print("ERROR: the server answered a cross-site request normally - it is running code")
    print("       without the guard. Restart the app on the current source, or use --self-host.")
    sys.exit(1)
print("  guard is active")


# ============================================================================
step("1. Legitimate callers still get through")
allowed("script/curl (no browser headers at all)")
allowed("address bar (Sec-Fetch-Site: none)", [("Sec-Fetch-Site", "none")])
allowed("API's own help page (same-origin, matching Origin)",
        [("Sec-Fetch-Site", "same-origin"), ("Origin", SELF)])
allowed("same-origin GET without Origin (what fetch() sends)", [("Sec-Fetch-Site", "same-origin")])
allowed("via localhost name (Host + Origin both localhost)",
        [("Sec-Fetch-Site", "same-origin"), ("Origin", f"http://localhost:{PORT}")],
        host=f"localhost:{PORT}")
allowed("Host name in capitals (hosts are case-insensitive)", host=f"LOCALHOST:{PORT}")
allowed("no Host header at all (bare HTTP client)", host="")
status, r, _ = raw("GET", f"/{FAKE}/get_tokens")
ok("script GET get_tokens -> 405 (get_tokens is POST-only)",
   status == 405, detail=f"got {status} {r}")
status, r, _ = raw("POST", f"/{FAKE}/get_tokens")
ok("script POST get_tokens reaches the route (404 project_not_open, not 403)",
   status == 404 and (r or {}).get("error") == "project_not_open", detail=f"got {status} {r}")
status, r, _ = raw("POST", "/projects/new", {})
ok("script POST /projects/new with empty body reaches the route (400 validation, not 403)",
   status == 400, detail=f"got {status} {r}")


# ============================================================================
step("2. What real browsers send from another page")
blocked_everywhere("Sec-Fetch-Site: cross-site (any other website)", [("Sec-Fetch-Site", "cross-site")])
blocked_everywhere("Sec-Fetch-Site: same-site (another port on 127.0.0.1)", [("Sec-Fetch-Site", "same-site")])
blocked_everywhere("<img>/<script> tag from another site (no Origin)",
                   [("Sec-Fetch-Site", "cross-site"), ("Sec-Fetch-Mode", "no-cors"),
                    ("Sec-Fetch-Dest", "image")])
blocked_everywhere("form POST from another site",
                   [("Sec-Fetch-Site", "cross-site"), ("Origin", "https://evil.example")])
blocked_everywhere("fetch() from :9000 test page",
                   [("Sec-Fetch-Site", "same-site"), ("Origin", "http://127.0.0.1:9000")])
blocked_everywhere("local file:// page (Origin: null)", [("Origin", "null")])
blocked_everywhere("sandboxed iframe (Origin: null, cross-site)",
                   [("Sec-Fetch-Site", "cross-site"), ("Origin", "null")])
blocked_everywhere("old browser without Sec-Fetch-* (Origin only)", [("Origin", "https://evil.example")])
blocked_everywhere("top-level navigation from a link on another site",
                   [("Sec-Fetch-Site", "cross-site"), ("Sec-Fetch-Mode", "navigate"),
                    ("Sec-Fetch-User", "?1")])


# ============================================================================
step("3. Origin look-alikes")
lookalikes = [
    f"http://localhost:{PORT}",            # same server, different origin
    f"http://[::1]:{PORT}",
    f"https://127.0.0.1:{PORT}",           # scheme differs
    "http://127.0.0.1",                    # port missing
    f"http://127.0.0.1:{PORT + 1}",
    f"http://127.0.0.1:{PORT}.evil.com",
    f"http://127.0.0.1:{PORT}@evil.com",
    f"http://evil.com/http://127.0.0.1:{PORT}",
    f"http://evil.com#http://127.0.0.1:{PORT}",
    f"{SELF}/",                            # trailing slash
    # (no leading/trailing-space variants: HTTP strips header whitespace,
    # so " http://127.0.0.1:8765" IS this server's origin, correctly allowed)
    SELF.upper(),
    f"{SELF}, http://evil.com",            # comma list in one header
    "http://0.0.0.0:%d" % PORT,
    "http://2130706433:%d" % PORT,         # 127.0.0.1 as an integer
    "chrome-extension://abcdefghijklmnop",
    "moz-extension://1234",
    "*",
]
for o in lookalikes:
    blocked_everywhere(f"Origin {o!r}", [("Origin", o)])


# ============================================================================
step("4. DNS rebinding (evil name resolving to 127.0.0.1 - page is 'same-origin' to itself)")
for evil_host in [f"evil.com:{PORT}", f"127.0.0.1.evil.com:{PORT}", f"localhost.evil.com:{PORT}",
                  f"127.0.0.1:{PORT}.evil.com", f"7f000001.rbndr.us:{PORT}", "evil.com",
                  f"0.0.0.0:{PORT}", f"127.0.0.2:{PORT}", f"[::ffff:127.0.0.1]:{PORT}"]:
    origin = "http://" + evil_host
    blocked_everywhere(f"Host {evil_host!r} + matching Origin + same-origin",
                       [("Sec-Fetch-Site", "same-origin"), ("Origin", origin)], host=evil_host)
    blocked_everywhere(f"Host {evil_host!r}, same-origin GET with no Origin",
                       [("Sec-Fetch-Site", "same-origin")], host=evil_host)
blocked_everywhere("right name, wrong port (Host 127.0.0.1:1)", host="127.0.0.1:1")
blocked_everywhere("Host with junk after the port", host=f"127.0.0.1:{PORT}/x")


# ============================================================================
step("5. Header games no browser plays (must still fail closed)")
for v in ["Cross-Site", "CROSS-SITE", " cross-site", "cross-site ", "cross-site\t",
          "cross-site, none", "none, cross-site", "garbage", "", "same-site;q=1"]:
    blocked_everywhere(f"Sec-Fetch-Site {v!r}", [("Sec-Fetch-Site", v)])
blocked_everywhere("two Sec-Fetch-Site headers: none then cross-site",
                   [("Sec-Fetch-Site", "none"), ("Sec-Fetch-Site", "cross-site")])
blocked_everywhere("two Sec-Fetch-Site headers: cross-site then none",
                   [("Sec-Fetch-Site", "cross-site"), ("Sec-Fetch-Site", "none")])
blocked_everywhere("two Origins: own first, evil second",
                   [("Origin", SELF), ("Origin", "http://evil.com")])
blocked_everywhere("two Origins: evil first, own second",
                   [("Origin", "http://evil.com"), ("Origin", SELF)])
blocked_everywhere("header names in odd case",
                   [("sec-fetch-site", "cross-site"), ("ORIGIN", "http://evil.com")])
blocked_everywhere("same-origin claim contradicted by Origin",
                   [("Sec-Fetch-Site", "same-origin"), ("Origin", "http://evil.com")])
blocked_everywhere("none claim contradicted by Origin",
                   [("Sec-Fetch-Site", "none"), ("Origin", "http://evil.com")])
blocked_everywhere("Referer from evil + cross-site",
                   [("Sec-Fetch-Site", "cross-site"), ("Referer", "http://evil.com/x")])
blocked_everywhere("X-Forwarded-Host spoof doesn't help",
                   [("X-Forwarded-Host", "evil.com"), ("Origin", "http://evil.com")])

status, r, _ = raw("GET", "/projects/active", [("Origin", "http://" + "a" * 8000 + ".com")])
ok("8 KB Origin -> refused (403/400/431), never 200/500",
   status in (400, 403, 431) or status == -1, detail=f"got {status}")
status, r, _ = raw("GET", "/projects/active", [("Origin", "http://évil.com".encode("utf-8").decode("latin-1"))])
ok("non-ASCII Origin -> refused, never 500", status in (400, 403), detail=f"got {status}")
status, r, _ = raw("GET", "/projects/active", host="évil.com".encode("utf-8").decode("latin-1"))
ok("non-ASCII Host -> refused, never 500", status in (400, 403), detail=f"got {status}")


# ============================================================================
step("6. Replies never let a page read them")
leaks = []
for method, path, body in TARGETS:
    for hdrs in ([("Origin", "http://evil.com")], [("Origin", "null")], [],
                 [("Origin", SELF), ("Sec-Fetch-Site", "same-origin")]):
        _, _, h = raw(method, path, hdrs, body)
        if any(k.startswith("access-control-") for k in h):
            leaks.append(f"{method} {path} {hdrs}")
ok("no Access-Control-* header on any reply", not leaks, detail="; ".join(leaks[:3]))
status, _, h = raw("OPTIONS", f"/{FAKE}/get_tokens",
                   [("Origin", "http://evil.com"), ("Access-Control-Request-Method", "POST"),
                    ("Access-Control-Request-Headers", "X-API-Token")])
ok("CORS preflight from evil.com -> 403, no allow headers",
   status == 403 and "access-control-allow-origin" not in h, detail=f"got {status} {h}")


# ============================================================================
step("7. Flood of blocked requests, then the server still works")
attack_headers = [[("Sec-Fetch-Site", "cross-site")], [("Origin", "http://evil.com")],
                  [("Origin", "null")]]
jobs = [(TARGETS[i % len(TARGETS)], attack_headers[i % 3]) for i in range(600)]


def _one(job):
    (method, path, body), hdrs = job
    s, r, _ = raw(method, path, hdrs, body, timeout=30)
    return s == 403 if method == "HEAD" else is_blocked(s, r), s


with ThreadPoolExecutor(max_workers=40) as pool:
    results = list(pool.map(_one, jobs))
bad = [s for good, s in results if not good]
ok(f"600 concurrent attack requests (40 threads) -> all 403", not bad,
   detail=f"{len(bad)} not blocked, statuses {sorted(set(bad))}")
allowed("legit request right after the flood")
status, r, _ = raw("POST", f"/{FAKE}/get_tokens")
ok("get_tokens still reachable by scripts after the flood (404 for fake project)",
   status == 404, detail=f"got {status}")


sys.exit(summary())
