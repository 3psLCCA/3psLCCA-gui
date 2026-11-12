"""
devtools/test apis/get_tokens_consent.test.py

Short interactive check of the get_tokens Allow/Deny popup.
You will click 3 popups: ALLOW, DENY, DENY.

  1. Allow  -> 200 + a key that works from this process, and is refused
     (401) when another process sends it.
  2. Deny   -> 403 denied.
  3. Two requests at once -> only ONE popup; the other gets 409.

Restart the app first so it runs the current code, then:
    python "devtools/test apis/get_tokens_consent.test.py"
"""

import subprocess
import sys
import threading
import time

from _common import call, step, ok, summary

POPUP_TIMEOUT = 150.0


def new_project(label):
    status, schema = call("GET", "/projects/new")
    if status != 200:
        print(f"  could not read /projects/new: {schema}")
        sys.exit(1)
    country = schema["fields"]["country"]["options"][0]
    name = f"consent test - {label} - {time.strftime('%H:%M:%S')}"
    status, r = call("POST", "/projects/new", body={"project_name": name, "country": country})
    if status != 200:
        print(f"  could not create project: {r}")
        sys.exit(1)
    print(f"  created '{name}'")
    return r["project_id"]


def ask_token(project_id):
    return call("POST", f"/{project_id}/get_tokens", timeout=POPUP_TIMEOUT)


def wait_enter(msg):
    try:
        input(f"\n>>> {msg}\n    Press Enter to send the request... ")
    except EOFError:
        pass


def yes(msg):
    try:
        return input(f"\n>>> {msg} (y/n): ").strip().lower().startswith("y")
    except EOFError:
        return False


status, _ = call("GET", "/projects/active")
if status != 200:
    print("ERROR: app not reachable on http://127.0.0.1:8765 - start it first.")
    sys.exit(1)


step("1. Allow")
p1 = new_project("allow")
wait_enter("A popup will appear. Check its 'Requested by' box, then click ALLOW.")
status, r = ask_token(p1)
ok("Allow -> 200 with a token", status == 200 and r.get("token"), detail=f"{status} {r}")
token = r.get("token")
ok("popup named this Python process under 'Requested by'",
   yes("Did the popup show python.exe and a PID under 'Requested by'?"))

status, r = call("GET", f"/{p1}/general_info", token=token)
ok("token works on a real endpoint", status == 200, detail=f"{status}")

other = subprocess.run(
    [sys.executable, "-c",
     "import sys,urllib.request,urllib.error\n"
     "r=urllib.request.Request(sys.argv[1],headers={'X-API-Token':sys.argv[2]})\n"
     "try: print(urllib.request.urlopen(r,timeout=10).status)\n"
     "except urllib.error.HTTPError as e: print(e.code)",
     f"http://127.0.0.1:8765/{p1}/general_info", token],
    capture_output=True, text=True, timeout=30,
).stdout.strip()
ok("same key sent from ANOTHER process -> 401", other == "401", detail=other)
ok("File -> API Access lists python under 'Programs you allowed' and shows "
   "the refused attempt in red under 'Recent activity'",
   yes("Open File -> API Access for this project. Is python listed, and is "
       "there a red REFUSED line?"))


step("2. Deny")
p2 = new_project("deny")
wait_enter("A popup will appear. Click DENY.")
status, r = ask_token(p2)
ok("Deny -> 403 denied", status == 403 and r.get("error") == "denied", detail=f"{status} {r}")


step("3. Two requests at once")
wait_enter("Two requests go out together. Only ONE popup should appear. Click DENY.")
results = {}


def fire(tag):
    results[tag] = ask_token(p2)


threads = [threading.Thread(target=fire, args=(t,)) for t in ("A", "B")]
for t in threads:
    t.start()
    time.sleep(0.05)
for t in threads:
    t.join(POPUP_TIMEOUT + 10)

statuses = sorted(s for s, _ in results.values())
ok("both requests returned", len(results) == 2, detail=str(results))
ok("one got 403 denied (the popup), the other 409 prompt_already_open (no second popup)",
   statuses == [403, 409], detail=f"statuses={statuses}")
ok("only one popup appeared", yes("Did exactly ONE popup appear?"))


sys.exit(summary())
