"""
gui/api/caller_identity.py

Works out which local program sent an API request, so the get_tokens
Allow/Deny popup can say WHO is asking instead of just "an external
application". Without this, any process on the machine could race the
user's own script to /get_tokens and be handed the token by a user who
assumed the popup was for their script.

How: the request arrives over a loopback TCP connection. Its client end
(REMOTE_ADDR:REMOTE_PORT) is a socket owned by the calling process, and the
OS connection table (psutil.net_connections) maps that socket to a PID.

Limits, stated plainly in the popup's wording too:
  - This identifies the PROGRAM (exe path + command line), not a person.
    A malicious program can still be named "python.exe"; the full path and
    command line are what make it recognisable.
  - Details of processes owned by another Windows user may be hidden by
    the OS (AccessDenied) - those fields come back as None and the popup
    shows them as unknown, which is itself a warning sign.
"""

from __future__ import annotations

try:
    import psutil
except ImportError:  # pragma: no cover - psutil is a declared dependency
    psutil = None

_MAX_CMDLINE_CHARS = 400


def caller_pid(remote_addr, remote_port, server_port) -> int | None:
    """PID of the process that owns the client end of this request's
    loopback connection, or None. Never raises. About 1 ms."""
    if psutil is None:
        return None
    try:
        remote_port = int(remote_port)
        server_port = int(server_port)
    except (TypeError, ValueError):
        return None
    try:
        conns = psutil.net_connections(kind="tcp4")
    except Exception:
        return None
    for c in conns:
        if not c.laddr or not c.raddr:
            continue
        if (c.laddr.port == remote_port and c.raddr.port == server_port
                and (remote_addr is None or c.laddr.ip == remote_addr)):
            return c.pid or None
    return None


def identify_caller(remote_addr, remote_port, server_port) -> dict | None:
    """Returns {"pid", "started", "name", "exe", "cmdline", "username"} for
    the process on the other end of this request's connection, or None if
    psutil is unavailable. "started" is the process start time, used with
    the PID to tie a token to this exact process. Never raises."""
    if psutil is None:
        return None
    pid = caller_pid(remote_addr, remote_port, server_port)
    if not pid:
        return {"pid": None, "started": None, "name": None, "exe": None, "cmdline": None, "username": None}

    info = {"pid": pid, "started": None, "name": None, "exe": None, "cmdline": None, "username": None}
    try:
        proc = psutil.Process(pid)
    except Exception:
        return info
    for key, getter in (
        ("name", proc.name),
        ("exe", proc.exe),
        ("cmdline", lambda: " ".join(proc.cmdline())),
        ("username", proc.username),
        ("started", proc.create_time),
    ):
        try:
            info[key] = getter() or None
        except Exception:
            pass
    if info["cmdline"] and len(info["cmdline"]) > _MAX_CMDLINE_CHARS:
        info["cmdline"] = info["cmdline"][:_MAX_CMDLINE_CHARS] + "..."
    return info
