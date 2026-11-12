"""
devtools/test apis/hardening.test.py

Brutal regression test for the fixes made after an independent attack
review of the local API:

  A. Path traversal in POST /projects/open (project_id used as a folder name)
  B. get_tokens popup: names the calling program, escapes HTML, one popup
     per project at a time, app-wide popup cap
  C. Single-threaded server (one stalled client froze everyone)
  D. Image URL fetching reaching internal addresses (SSRF), redirects,
     proxies, chatty error messages
  E. Unbounded request bodies and decompression-bomb images
  F. Unauthenticated project-creation / open spam
  G. get_tokens reachable via GET (old browsers + <img> tags)
  H. Internal exception text leaking to callers

Part 1 runs the hardened functions directly, in this process (no app or
network needed). Part 2 talks HTTP to a server:
  - default: the running GUI at 127.0.0.1:8765 (must be on the new code -
    the test checks and stops otherwise);
  - --self-host: starts the current server.py on a spare port with a stub
    bridge (no GUI; the traversal-over-HTTP and Qt checks then rely on
    part 1).

Never shows a popup and never creates or opens a project in live mode:
the rate-limit and 413 checks that would need real creations only run
under --self-host, and every /projects/open payload in live mode is one
that must be rejected before touching the disk.

Run:
    python "devtools/test apis/hardening.test.py" --self-host
    python "devtools/test apis/hardening.test.py"            (against the app)
"""

import argparse
import base64
import http.client
import http.server
import io
import json
import os
import socket
import sys
import threading
import time

from _common import step, ok, summary

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
parser.add_argument("--self-host", action="store_true",
                    help="start server.py from source on a spare port with a stub bridge (no GUI)")
args = parser.parse_args()


def expect_raises(fn, exc_types):
    try:
        fn()
    except exc_types as e:
        return True, e
    except Exception as e:  # wrong exception type
        return False, e
    return False, None


# ============================================================================
# PART 1 - in-process
# ============================================================================
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

_qapp = QApplication.instance() or QApplication([])

from three_ps_lcca_gui.gui.api import bridge as bridge_mod  # noqa: E402
from three_ps_lcca_gui.gui.api import image_upload  # noqa: E402
from three_ps_lcca_gui.gui.api import tokens  # noqa: E402
from three_ps_lcca_gui.gui.api.caller_identity import identify_caller  # noqa: E402
from three_ps_lcca_gui.gui.api.server import _RateLimiter  # noqa: E402
from three_ps_lcca_gui.gui.components.api_access_prompt import ApiAccessPrompt  # noqa: E402

# ----------------------------------------------------------------------------
step("A. project_id can never leave the projects folder")
BAD_IDS = [
    "..", ".", "...", "../x", "..\\x", "..\\..\\Windows", "../../etc/passwd",
    "C:\\Windows", "C:/Windows", "C:", "C:x", "c:\\", "\\\\attacker\\share\\p",
    "//attacker/share/p", "\\\\?\\C:\\Windows", "\\\\.\\pipe\\x", "/abs", "\\abs",
    "proj_1/..", "proj_1\\..\\..", "a/b", "a\\b", "proj_\x00", "proj_\n", "proj_\t",
    "proj_1 ", "proj_1.", " proj_1", "-rf", "_x", "x" * 129, "", "CON", "NUL",
    "COM1", "LPT1", "AUX", "PRN", "con.txt", "proj:stream", "proj_1::$DATA",
    "proj*", "proj?", "proj<", "proj>", "proj|", "proj\"", "%2e%2e", "proj_%00",
    "\u2025", "\uff0e\uff0e", "proj_\u202e", "proj_\u00e9",
    None, 123, ["proj_1"], {"a": 1},
]
leaks = [repr(b) for b in BAD_IDS if bridge_mod._is_safe_project_id(b)]
ok(f"{len(BAD_IDS)} hostile project ids all rejected", not leaks, detail=", ".join(leaks[:8]))
GOOD_IDS = ["proj_0cf0bfe3", "proj_1969a133", "My Project 1", "imported-2024.v2", "a"]
refused = [g for g in GOOD_IDS if not bridge_mod._is_safe_project_id(g)]
ok("real-looking project ids still accepted", not refused, detail=str(refused))

# ----------------------------------------------------------------------------
step("B. get_tokens popup: says who is asking, can't be restyled")
srv = socket.socket()
srv.bind(("127.0.0.1", 0))
srv.listen(1)
sport = srv.getsockname()[1]
cli = socket.create_connection(("127.0.0.1", sport))
conn, (raddr, rport) = srv.accept()
info = identify_caller(raddr, rport, sport)
ok("identify_caller finds THIS process as the caller of a loopback connection",
   info is not None and info.get("pid") == os.getpid(), detail=str(info))
ok("...with its exe path and command line",
   bool(info and info.get("exe") and info.get("cmdline")), detail=str(info))
for c in (cli, conn, srv):
    c.close()
ok("identify_caller on a port nobody owns -> pid None, no crash",
   (identify_caller("127.0.0.1", 1, 2) or {}).get("pid") is None)
ok("identify_caller with junk input -> None, no crash",
   identify_caller(None, "abc", None) is None)

evil = '<span style="color:green;font-size:30px">VERIFIED by Windows Security</span><img src=x>'
dlg = ApiAccessPrompt(evil, caller={"pid": 4242, "name": "<b>trusted</b>.exe",
                                    "exe": "C:\\x\\<i>a</i>.exe", "cmdline": "a & <script>",
                                    "username": "u"})
all_text = "\n".join(w.text() for w in dlg.findChildren(QLabel))
ok("project name is HTML-escaped in the popup (no live tags)",
   "<span" not in all_text and "&lt;span" in all_text, detail=all_text[:200])
ok("caller name/exe/cmdline are HTML-escaped",
   "<b>trusted</b>" not in all_text and "&lt;b&gt;trusted" in all_text
   and "<script>" not in all_text, detail=all_text[:300])
ok("popup shows the caller's PID", "PID 4242" in all_text)
unknown = ApiAccessPrompt._describe_caller(None)
ok("unidentifiable caller -> explicit warning in the popup", "could not identify" in unknown)
ok("caller with a non-int PID can't break the dialog",
   expect_raises(lambda: ApiAccessPrompt._describe_caller({"pid": "1<b>"}), (ValueError,))[0])
dlg.deleteLater()

# App-wide popup cap (state is per-process; this is a fresh process).
allowed = [tokens.can_prompt(f"cap_probe_{i}") for i in range(tokens.GLOBAL_PROMPT_LIMIT + 3)]
ok(f"app-wide cap: {tokens.GLOBAL_PROMPT_LIMIT} popups per minute across ALL projects, then refused",
   allowed == [True] * tokens.GLOBAL_PROMPT_LIMIT + [False] * 3, detail=str(allowed))
wait = tokens.global_retry_after()
ok("app-wide cap reports how long to wait (so callers can retry instead of giving up)",
   0 < wait <= tokens.GLOBAL_PROMPT_WINDOW_S, detail=f"wait={wait}")
for i in range(tokens.GLOBAL_PROMPT_LIMIT + 3):
    tokens.clear_token(f"cap_probe_{i}")
tokens._recent_prompts.clear()
ok("app-wide cap reports no wait once the window is clear", tokens.global_retry_after() == 0.0)


class _Win:
    _frozen = False

    def isMinimized(self):
        return False


b = bridge_mod.ApiBridge.__new__(bridge_mod.ApiBridge)
b._prompting = {"busy_proj"}
b._find_window = lambda pid: _Win()
r = bridge_mod.ApiBridge._get_tokens(b, "busy_proj", {"caller": None})
ok("second get_tokens while a popup is open -> prompt_already_open, no second popup",
   r.get("error") == "prompt_already_open", detail=str(r))

# ----------------------------------------------------------------------------
step("H. Unexpected exceptions don't leak details")


class _ExplodingManager:
    def __getattr__(self, name):
        raise RuntimeError("C:\\Users\\victim\\secret\\path.json is corrupt (token=abc123)")


import queue  # noqa: E402

b2 = bridge_mod.ApiBridge(_ExplodingManager())
q = queue.Queue()
import contextlib  # noqa: E402

with contextlib.redirect_stderr(io.StringIO()):  # traceback goes to the app log
    b2._handle("get", "proj_x", "general_info", None, q)
res = q.get_nowait()
blob = json.dumps(res)
ok("exception -> generic internal_error", res.get("error") == "internal_error", detail=blob)
ok("no path / secret / exception text in the reply",
   "victim" not in blob and "abc123" not in blob and "corrupt" not in blob, detail=blob)

# ----------------------------------------------------------------------------
step("D. Image URLs can't reach internal addresses")
from three_ps_lcca_gui.gui.api.image_upload import _BlockedAddress, _FetchFailed  # noqa: E402

INTERNAL = [
    "http://127.0.0.1:8765/projects", "http://localhost/", "http://127.1/", "http://0.0.0.0/",
    "http://2130706433/", "http://0x7f000001/", "http://017700000001/", "http://[::1]/",
    "http://[::ffff:127.0.0.1]/", "http://[0:0:0:0:0:ffff:7f00:1]/", "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.1/", "http://172.16.0.1/", "http://192.168.1.1/", "http://100.64.0.1/",
    "http://[fe80::1]/", "http://[fc00::1]/", "http://224.0.0.1/", "http://255.255.255.255/",
    "http://198.18.0.1/", "https://127.0.0.1:443/", "http://user:pw@127.0.0.1/",
    "http://127.0.0.1#@example.com/", "http://localhost.:8765/",
]
fails = []
for url in INTERNAL:
    good, e = expect_raises(lambda: image_upload._fetch(url), (_BlockedAddress, _FetchFailed))
    if not good:
        fails.append(f"{url} -> {e!r}")
ok(f"{len(INTERNAL)} internal/loopback/metadata URLs all refused", not fails, detail="; ".join(fails[:5]))
for url in ["ftp://example.com/x.png", "file:///C:/Windows/win.ini", "gopher://x/", "data:image/png;base64,AA==",
            "http:///nohost", "javascript:alert(1)"]:
    good, e = expect_raises(lambda: image_upload._fetch(url), (_BlockedAddress, _FetchFailed))
    ok(f"non-http(s) / malformed URL refused: {url[:30]}", good, detail=repr(e))

# Redirect + error-message checks need a reachable server, so briefly
# let loopback through and stand one up locally.


class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()
        elif self.path == "/500":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"internal secret stacktrace")
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<html>not an image</html>")

    def log_message(self, *a):
        pass


hs = http.server.HTTPServer(("127.0.0.1", 0), _H)
threading.Thread(target=hs.serve_forever, daemon=True).start()
hp = hs.server_address[1]
_real_check = image_upload._check_public_ip
image_upload._check_public_ip = lambda ip: None
try:
    good, e = expect_raises(lambda: image_upload._fetch(f"http://127.0.0.1:{hp}/redirect"), (_FetchFailed,))
    ok("redirects are not followed", good, detail=repr(e))
    good, e = expect_raises(lambda: image_upload._fetch(f"http://127.0.0.1:{hp}/500"), (_FetchFailed,))
    ok("HTTP error -> generic failure (no status/body echoed)", good and not str(e), detail=repr(e))
    os.environ["HTTP_PROXY"] = os.environ["http_proxy"] = "http://127.0.0.1:1"
    try:
        data = image_upload._fetch(f"http://127.0.0.1:{hp}/ok")
        ok("system proxy settings are ignored", data.startswith(b"<html>"))
    except Exception as ex:
        ok("system proxy settings are ignored", False, detail=repr(ex))
    finally:
        os.environ.pop("HTTP_PROXY", None)
        os.environ.pop("http_proxy", None)
finally:
    image_upload._check_public_ip = _real_check
    hs.shutdown()

# Error text returned to the caller through resolve_image_urls.
logo_key = None
for chunk, entry in image_upload.CHUNK_PAGE_MAP.items():
    for fd in entry.get("field_defs") or []:
        if getattr(fd, "field_type", None) == "upload_img":
            logo_key = (chunk, fd.key)
            break
    if logo_key:
        break
if logo_key:
    chunk, key = logo_key
    msgs = []
    for url in ["http://127.0.0.1:22/", "http://10.1.2.3:3306/", f"http://192.0.2.1:9/",
                "http://no-such-host.invalid/"]:
        _, errs = image_upload.resolve_image_urls(chunk, {key: url})
        msgs.append(errs[0] if errs else "")
    ok("all failure messages give no port/connection detail",
       all(m and "refused" not in m.lower() and "errno" not in m.lower() and "timed out" not in m.lower()
           and "getaddrinfo" not in m.lower() for m in msgs), detail=" | ".join(msgs))
    ok("internal targets and an unreachable public host can't be told apart by open/closed port",
       len({m for m in msgs[:2]}) == 1, detail=" | ".join(msgs[:2]))
else:
    print("  (no upload_img field registered - resolve_image_urls message checks skipped)")

# ----------------------------------------------------------------------------
step("E. Decompression bombs are refused")
from PIL import Image  # noqa: E402

buf = io.BytesIO()
Image.new("1", (10000, 10000)).save(buf, "PNG", optimize=True)
bomb = buf.getvalue()
print(f"  bomb: {len(bomb):,} bytes on disk, 100,000,000 pixels decoded")
good, e = expect_raises(lambda: image_upload._validate_base64_image(base64.b64encode(bomb).decode()), (ValueError,))
ok("100-megapixel PNG (a few KB) refused before decoding", good and "pixels" in str(e), detail=repr(e))
buf = io.BytesIO()
Image.new("1", (15000, 15000)).save(buf, "PNG", optimize=True)
good, e = expect_raises(lambda: image_upload._validate_base64_image(base64.b64encode(buf.getvalue()).decode()),
                        (ValueError,))
ok("225-megapixel PNG (past Pillow's own hard limit) -> clean ValueError, not an unhandled crash",
   good, detail=repr(e))
buf = io.BytesIO()
Image.new("RGB", (400, 200), "white").save(buf, "PNG")
good, e = expect_raises(lambda: image_upload._validate_base64_image(base64.b64encode(buf.getvalue()).decode()),
                        (Exception,))
ok("normal 400x200 logo still accepted", not good, detail=repr(e))

# ----------------------------------------------------------------------------
step("F. Rate limiter logic")
rl = _RateLimiter(3, 0.5)
seq = [rl.allow() for _ in range(5)]
ok("3 per window, then refused", seq == [True, True, True, False, False], detail=str(seq))
ok("retry_after is positive while limited", rl.retry_after() >= 1)
time.sleep(0.6)
ok("window slides - allowed again afterwards", rl.allow())
rl = _RateLimiter(50, 60)
results = []
ts = [threading.Thread(target=lambda: results.append(rl.allow())) for _ in range(200)]
for t in ts:
    t.start()
for t in ts:
    t.join()
ok("200 racing threads -> exactly 50 allowed (thread-safe)", results.count(True) == 50,
   detail=f"{results.count(True)} allowed")


# ============================================================================
# PART 2 - over HTTP
# ============================================================================
HOST, PORT = "127.0.0.1", 8765
if args.self_host:
    import logging

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    from werkzeug.serving import make_server
    from three_ps_lcca_gui.gui.api import server as server_mod

    class _StubBridge:
        def call(self, name, *a, **kw):
            if name == "list_projects":
                return {"projects": []}
            if name == "create_project":
                return {"project_id": "proj_stub0000", "currency": "INR"}
            if name == "open_project":
                return {"ok": True, "status": "opening"}
            return {"error": "project_not_open", "message": "stub"}

    with socket.socket() as s:
        s.bind((HOST, 0))
        PORT = s.getsockname()[1]
    _httpd = make_server(HOST, PORT, server_mod._create_app(_StubBridge()), threaded=True)
    threading.Thread(target=_httpd.serve_forever, daemon=True).start()
    print(f"\n  self-hosted current server.py on {HOST}:{PORT}")


def raw(method, path, body=None, headers=(), timeout=15.0):
    c = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
    try:
        data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
        hdrs = {"Content-Type": "application/json", **dict(headers)}
        c.request(method, path, body=data, headers=hdrs)
        resp = c.getresponse()
        rb = resp.read()
        try:
            return resp.status, json.loads(rb), dict(resp.getheaders())
        except Exception:
            return resp.status, None, dict(resp.getheaders())
    except (OSError, http.client.HTTPException) as e:
        return -1, {"_err": repr(e)}, {}
    finally:
        c.close()


step("0. Server reachable and on the hardened code")
status, _, _ = raw("GET", "/projects/active")
if status != 200:
    print(f"ERROR: no API server at {HOST}:{PORT}. Start the app, or use --self-host.")
    sys.exit(summary() or 1)
status, _, _ = raw("GET", "/fake_hardening_probe/get_tokens")
if status != 405:
    print("ERROR: GET /get_tokens did not return 405 - this server is running the old code.")
    print("       Restart the app on the current source, or use --self-host.")
    sys.exit(1)
print("  hardened server detected")

# ----------------------------------------------------------------------------
step("G. get_tokens is POST-only")
for m in ("GET", "HEAD"):
    status, r, h = raw(m, "/fake_hardening_probe/get_tokens")
    ok(f"{m} /<id>/get_tokens -> 405", status == 405, detail=f"got {status}")
status, r, h = raw("GET", "/fake_hardening_probe/get_tokens")
ok("405 body is JSON naming POST, with an Allow header",
   (r or {}).get("error") == "method_not_allowed" and "POST" in (r or {}).get("allowed_methods", [])
   and "POST" in h.get("Allow", ""), detail=f"{r} {h.get('Allow')}")
status, r, _ = raw("POST", "/fake_hardening_probe/get_tokens")
ok("POST still reaches the route (404 project_not_open for an unknown id)",
   status == 404 and (r or {}).get("error") == "project_not_open", detail=f"{status} {r}")

# ----------------------------------------------------------------------------
step("C. One stalled client can't freeze the API")
stalls = []
for _ in range(5):
    s = socket.create_connection((HOST, PORT))
    s.sendall(b"POST /projects/open HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 1000\r\n\r\n{")
    stalls.append(s)
t0 = time.monotonic()
status, _, _ = raw("GET", "/projects/active", timeout=5)
dt = time.monotonic() - t0
ok(f"with 5 half-sent requests hanging, a normal request still answers ({dt:.2f}s)",
   status == 200 and dt < 3, detail=f"status {status} after {dt:.1f}s")
for s in stalls:
    s.close()

# ----------------------------------------------------------------------------
step("E. Request size limit")
big = b'{"project_id": "' + b"A" * (33 * 1024 * 1024) + b'"}'
status, r, _ = raw("POST", "/projects/open", body=big, timeout=60)
ok("33 MB body -> 413 payload_too_large (JSON)",
   status == 413 and (r or {}).get("error") == "payload_too_large", detail=f"{status} {str(r)[:120]}")
status, r, _ = raw("POST", "/projects/open", body=b"x", headers={"Content-Length": str(10 ** 12)}, timeout=10)
ok("Content-Length of 1 TB declared -> refused up front, server alive",
   status in (413, -1) and raw("GET", "/projects/active")[0] == 200, detail=f"{status}")

# ----------------------------------------------------------------------------
step("A. Path traversal over HTTP")
if args.self_host:
    print("  (stub bridge has no filesystem - covered by part 1)")
else:
    sneaky = ["..", "..\\..\\Windows", "C:\\Windows", "\\\\127.0.0.1\\c$", "//localhost/c$",
              "../../../../etc", "C:", "CON", "proj_1/../..", "\\\\?\\C:\\"]
    bad = []
    for pid in sneaky:
        status, r, _ = raw("POST", "/projects/open", {"project_id": pid})
        if not (status == 404 and (r or {}).get("error") == "project_not_found"):
            bad.append(f"{pid!r} -> {status} {r}")
    ok(f"{len(sneaky)} traversal/absolute/UNC ids -> 404 project_not_found", not bad, detail="; ".join(bad[:3]))

# ----------------------------------------------------------------------------
step("F. Project creation / open spam is rate limited")
if not args.self_host:
    print("  (live app: skipped - would create real projects. Run with --self-host.)")
else:
    from three_ps_lcca_gui.gui.components.utils.countries_data import COUNTRIES

    statuses = [raw("POST", "/projects/new", {"project_name": f"spam {i}", "country": COUNTRIES[0]})[0]
                for i in range(server_mod.PROJECT_CREATE_LIMIT + 5)]
    ok(f"/projects/new: first {server_mod.PROJECT_CREATE_LIMIT} ok, then 429",
       statuses[:server_mod.PROJECT_CREATE_LIMIT] == [200] * server_mod.PROJECT_CREATE_LIMIT
       and set(statuses[server_mod.PROJECT_CREATE_LIMIT:]) == {429}, detail=str(statuses))
    status, r, h = raw("POST", "/projects/new", {"project_name": "x", "country": COUNTRIES[0]})
    ok("429 carries Retry-After and rate_limited error",
       status == 429 and (r or {}).get("error") == "rate_limited" and int(h.get("Retry-After", 0)) > 0,
       detail=f"{status} {r} {h.get('Retry-After')}")
    status, r, _ = raw("POST", "/projects/new", {"project_name": "y" * 201, "country": COUNTRIES[0]})
    ok("201-char project name -> 400 (checked before the rate limit)", status == 400, detail=f"{status}")
    statuses = [raw("POST", "/projects/open", {"project_id": "proj_00000000"})[0]
                for _ in range(server_mod.PROJECT_OPEN_LIMIT + 3)]
    ok(f"/projects/open: first {server_mod.PROJECT_OPEN_LIMIT} ok, then 429",
       statuses.count(200) == server_mod.PROJECT_OPEN_LIMIT and statuses[-3:] == [429] * 3,
       detail=str(statuses[-6:]))
    statuses = [raw("POST", "/projects/new", {})[0] for _ in range(5)]
    ok("invalid bodies are never rate-limited (400, not 429)", statuses == [400] * 5, detail=str(statuses))

sys.exit(summary())
