"""
gui/api/auth.py

The one place a Flask route checks the request's X-API-Token (see tokens.py
for the two kinds of key). Shared by server.py and catalog.py.
"""

from flask import g, request

from . import tokens
from .caller_identity import caller_pid


def authorize_request(project_id: str | None = None) -> bool:
    """True if the request's token may act on project_id (None = any open
    project). On success, g.api_who holds who is calling, for the activity
    notice."""
    env = request.environ
    who = tokens.authorize(
        project_id,
        request.headers.get("X-API-Token"),
        lambda: caller_pid(env.get("REMOTE_ADDR"), env.get("REMOTE_PORT"), env.get("SERVER_PORT")),
        f"{request.method} {request.path}",
    )
    if who is None:
        return False
    g.api_who = who
    return True
