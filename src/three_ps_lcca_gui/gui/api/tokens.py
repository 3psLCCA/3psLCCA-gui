"""
gui/api/tokens.py

Who may use the local HTTP API, per open project. Two kinds of key:

Manual token (one per project)
  Shown in File -> API Access, for scripts and curl the user runs by hand.
  Works from any program, like a password. Created when the project opens,
  can be regenerated or revoked there, and dropped when the project closes.

Program grants (any number per project)
  Handed out by POST /<project_id>/get_tokens after the user clicks Allow
  in a popup that names the requesting program. Each Allow creates a NEW
  token that is tied to that one running process (PID + process start
  time): a request carrying it is accepted only if the OS says the request
  came from that same process. So a token copied by another program - from
  a log, a config file, memory dumps of a crashed process etc. - is
  useless to it, and it stops working when the process exits. Each grant
  is listed in File -> API Access with its own Revoke button.

  What this does NOT stop: malware running as the same Windows user can
  read project files directly or inject code into the granted process.
  The Windows account is the real boundary; the activity log below at
  least makes API changes visible.

Popup limits
  - Per project, at most MAX_PROMPTS popups may end without an Allow
    (Deny, close, timeout) per session. Allowed popups don't count, so a
    genuine tool that restarts can ask again. Past the cap, get_tokens is
    refused without a popup until the project is reopened.
  - App-wide, at most GLOBAL_PROMPT_LIMIT popups per GLOBAL_PROMPT_WINDOW_S,
    so opening many projects can't multiply the popups.

Activity
  Every authorised request is recorded per project (who + what), shown in
  File -> API Access; changes also flash in the project window's status bar.
"""

import collections
import secrets
import threading
import time
from dataclasses import dataclass, field

_lock = threading.Lock()
_tokens: dict[str, str] = {}  # { project_id: manual token }
_grants: dict[str, "Grant"] = {}  # { grant_id: Grant }
_denied_count: dict[str, int] = {}  # { project_id: popups that ended without Allow }
_activity: dict[str, collections.deque] = {}  # { project_id: deque[Activity] }

MAX_PROMPTS = 3
ACTIVITY_KEEP = 50
MANUAL_LABEL = "Your script token"

GLOBAL_PROMPT_LIMIT = 5
GLOBAL_PROMPT_WINDOW_S = 60.0
_recent_prompts: collections.deque[float] = collections.deque()


@dataclass
class Grant:
    grant_id: str
    project_id: str
    token: str
    pid: int
    started: float | None  # process create_time, guards against PID reuse
    name: str | None
    exe: str | None
    cmdline: str | None
    granted_at: float = field(default_factory=time.time)
    last_used: float | None = None
    last_action: str | None = None

    @property
    def label(self) -> str:
        return f"{self.name or 'unknown program'} (PID {self.pid})"


@dataclass
class Activity:
    when: float
    who: str
    action: str


# ── Manual token ───────────────────────────────────────────────────────────

def ensure_token(project_id: str) -> str:
    """Return the project's manual token, generating one on first call."""
    with _lock:
        token = _tokens.get(project_id)
        if token is None:
            token = secrets.token_urlsafe(24)
            _tokens[project_id] = token
        return token


def get_token(project_id: str) -> str | None:
    with _lock:
        return _tokens.get(project_id)


def regenerate(project_id: str) -> str:
    with _lock:
        token = secrets.token_urlsafe(24)
        _tokens[project_id] = token
        return token


def revoke_manual(project_id: str) -> None:
    with _lock:
        _tokens.pop(project_id, None)


def clear_token(project_id: str) -> None:
    """Drop ALL of this project's API-access state (manual token, program
    grants, popup count, activity) - called when the project window closes."""
    with _lock:
        _tokens.pop(project_id, None)
        _denied_count.pop(project_id, None)
        _activity.pop(project_id, None)
        for gid in [g.grant_id for g in _grants.values() if g.project_id == project_id]:
            del _grants[gid]


# ── Program grants ─────────────────────────────────────────────────────────

def add_grant(project_id: str, caller: dict) -> str:
    """Create a token tied to the calling process. `caller` comes from
    caller_identity.identify_caller() and must have a pid."""
    grant = Grant(
        grant_id=secrets.token_hex(6),
        project_id=project_id,
        token=secrets.token_urlsafe(24),
        pid=int(caller["pid"]),
        started=caller.get("started"),
        name=caller.get("name"),
        exe=caller.get("exe"),
        cmdline=caller.get("cmdline"),
    )
    with _lock:
        _grants[grant.grant_id] = grant
    _log(project_id, grant.label, "was given access (popup Allow)")
    return grant.token


def list_grants(project_id: str) -> list[Grant]:
    """This project's live grants, oldest first. Grants whose process has
    exited are removed on the way."""
    with _lock:
        mine = [g for g in _grants.values() if g.project_id == project_id]
    alive = []
    for g in mine:
        if _process_alive(g.pid, g.started):
            alive.append(g)
        else:
            with _lock:
                _grants.pop(g.grant_id, None)
    return sorted(alive, key=lambda g: g.granted_at)


def revoke_grant(grant_id: str) -> None:
    with _lock:
        g = _grants.pop(grant_id, None)
    if g is not None:
        _log(g.project_id, g.label, "access revoked in File -> API Access")


def _process_alive(pid: int, started: float | None) -> bool:
    try:
        import psutil
        proc = psutil.Process(pid)
        return started is None or abs(proc.create_time() - started) < 0.01
    except Exception:
        return False


# ── Checking a request ─────────────────────────────────────────────────────

def authorize(project_id: str | None, provided: str | None, caller_pid, action: str) -> str | None:
    """Return who is calling (a label) if `provided` may act on project_id,
    else None. project_id=None means "any open project" (catalog routes).

    caller_pid: zero-arg callable returning the PID that sent the request.
    Only called when the token is a program grant, since the lookup isn't
    free and the manual token isn't tied to a process."""
    if not provided:
        return None
    with _lock:
        if project_id is None:
            manual = [(pid, t) for pid, t in _tokens.items()]
        else:
            t = _tokens.get(project_id)
            manual = [(project_id, t)] if t else []
        grants = [g for g in _grants.values() if project_id is None or g.project_id == project_id]

    for pid_, token in manual:
        if secrets.compare_digest(token, provided):
            _log(pid_, MANUAL_LABEL, action)
            return MANUAL_LABEL

    for g in grants:
        if not secrets.compare_digest(g.token, provided):
            continue
        try:
            sender = caller_pid()
        except Exception:
            sender = None
        if sender != g.pid or not _process_alive(g.pid, g.started):
            _log(g.project_id, f"PID {sender or 'unknown'}",
                 f"REFUSED: used the key of {g.label}: {action}")
            return None
        with _lock:
            g.last_used = time.time()
            g.last_action = action
        _log(g.project_id, g.label, action)
        return g.label
    return None


# ── Activity log ───────────────────────────────────────────────────────────

def _log(project_id: str, who: str, action: str) -> None:
    with _lock:
        q = _activity.setdefault(project_id, collections.deque(maxlen=ACTIVITY_KEEP))
        q.append(Activity(time.time(), who, action))


def activity(project_id: str) -> list[Activity]:
    """Newest first."""
    with _lock:
        return list(reversed(_activity.get(project_id, ())))


# ── Popup limits ───────────────────────────────────────────────────────────

def global_retry_after() -> float:
    """Seconds until the app-wide popup cap lets another popup through
    (0.0 if one is allowed right now). Doesn't count as a prompt."""
    with _lock:
        now = time.monotonic()
        while _recent_prompts and now - _recent_prompts[0] >= GLOBAL_PROMPT_WINDOW_S:
            _recent_prompts.popleft()
        if len(_recent_prompts) < GLOBAL_PROMPT_LIMIT:
            return 0.0
        return max(0.0, GLOBAL_PROMPT_WINDOW_S - (now - _recent_prompts[0]))


def can_prompt(project_id: str) -> bool:
    """True (and counts the popup against the app-wide window) if this
    project hasn't used up its MAX_PROMPTS un-allowed popups and the app as
    a whole is under GLOBAL_PROMPT_LIMIT for the window."""
    with _lock:
        if _denied_count.get(project_id, 0) >= MAX_PROMPTS:
            return False
        now = time.monotonic()
        while _recent_prompts and now - _recent_prompts[0] >= GLOBAL_PROMPT_WINDOW_S:
            _recent_prompts.popleft()
        if len(_recent_prompts) >= GLOBAL_PROMPT_LIMIT:
            return False
        _recent_prompts.append(now)
        return True


def record_denied(project_id: str) -> None:
    """A popup ended without Allow (Deny, close, timeout)."""
    with _lock:
        _denied_count[project_id] = _denied_count.get(project_id, 0) + 1
