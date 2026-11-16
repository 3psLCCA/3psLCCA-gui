"""
gui/api/runtime.py

Turns the local API server on and off while the app is running, so the
Settings -> Local API toggle applies immediately instead of after a restart.

Deliberately light: nothing heavy is imported here. server.py (and with it
FastAPI/uvicorn) is only imported when the server is actually started, so a
disabled API adds nothing to startup time.

Every function runs on the Qt main thread.
"""

from three_ps_lcca_gui.gui._CONFIG import LOCAL_API_ENABLED

_manager = None  # ProjectManager, set once at startup
_handle = None   # server.ApiServerHandle while running


def init(manager, app, enabled: bool) -> None:
    """Called once at startup with the ProjectManager. Starts the server if
    the setting is on, and makes sure it is stopped when the app quits."""
    global _manager
    _manager = manager
    app.aboutToQuit.connect(_stop)
    set_enabled(enabled)


def set_enabled(enabled: bool) -> None:
    """Start or stop the server to match the setting. Does nothing before
    init() (e.g. from the first-launch dialog - startup reads the saved
    setting right after), or while the LOCAL_API_ENABLED kill switch is off.
    A failure to bind is logged by start_api_server and never raises."""
    if not LOCAL_API_ENABLED or _manager is None:
        return
    if enabled and _handle is None:
        _start()
    elif not enabled:
        _stop()


def active_port() -> int | None:
    """Port the server is listening on, or None when it isn't running."""
    return _handle.port if _handle is not None else None


def _start() -> None:
    global _handle
    from three_ps_lcca_gui.gui.api.server import start_api_server

    _handle = start_api_server(_manager)


def _stop() -> None:
    global _handle
    handle, _handle = _handle, None
    if handle is not None:
        handle.shutdown()
