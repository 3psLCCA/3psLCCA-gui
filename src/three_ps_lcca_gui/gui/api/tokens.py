"""
gui/api/tokens.py

Per-project bearer tokens for the local HTTP API. A token is generated the moment
a project becomes reachable (opened) and discarded when it's closed, so the API
can only ever address projects that are currently open in the GUI.
"""

import secrets
import threading

_lock = threading.Lock()
_tokens: dict[str, str] = {}


def ensure_token(project_id: str) -> str:
    """Return the token for project_id, generating one on first call."""
    with _lock:
        token = _tokens.get(project_id)
        if token is None:
            token = secrets.token_urlsafe(24)
            _tokens[project_id] = token
        return token


def get_token(project_id: str) -> str | None:
    with _lock:
        return _tokens.get(project_id)


def check_token(project_id: str, provided: str | None) -> bool:
    if not provided:
        return False
    with _lock:
        expected = _tokens.get(project_id)
    return expected is not None and secrets.compare_digest(expected, provided)


def check_any(provided: str | None) -> bool:
    """True if `provided` matches ANY currently-issued project token. Used to
    gate endpoints that aren't project-scoped (the material catalog search)
    but still shouldn't be reachable with zero projects open - the API's
    contract stays "only usable while at least one project is open"."""
    if not provided:
        return False
    with _lock:
        candidates = list(_tokens.values())
    return any(secrets.compare_digest(t, provided) for t in candidates)


def regenerate(project_id: str) -> str:
    with _lock:
        token = secrets.token_urlsafe(24)
        _tokens[project_id] = token
        return token


def clear_token(project_id: str) -> None:
    with _lock:
        _tokens.pop(project_id, None)
