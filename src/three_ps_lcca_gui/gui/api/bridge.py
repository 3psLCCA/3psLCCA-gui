"""
gui/api/bridge.py

ApiBridge marshals requests from the Flask worker thread onto the Qt main thread.
Flask handlers must never touch QWidgets directly - all GUI/engine interaction
goes through ApiBridge.call(), which blocks the calling (Flask) thread on a
queue.Queue while the actual work runs as a slot on the main thread.

Fully generic over whatever chunks are registered in registry.CHUNK_PAGE_MAP -
this file has no knowledge of Bridge Data or any other specific page. See
gui/api/pages/ for how pages register themselves, and registry.py for the
schema/validation logic that runs off the same registry.
"""

import queue

from PySide6.QtCore import QObject, Qt, Signal

from . import pages  # noqa: F401  (import triggers each page's registration)
from .registry import CHUNK_PAGE_MAP


class ApiBridge(QObject):
    _request = Signal(str, str, str, object, object)

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._request.connect(self._handle, Qt.QueuedConnection)

    def call(self, method: str, project_id: str, chunk: str, payload=None, timeout: float = 10.0) -> dict:
        """Thread-safe. Call from any thread; blocks until the main thread replies."""
        result_q: queue.Queue = queue.Queue(maxsize=1)
        self._request.emit(method, project_id, chunk, payload, result_q)
        try:
            return result_q.get(timeout=timeout)
        except queue.Empty:
            return {"error": "timeout"}

    # ── Runs on the Qt main thread ──────────────────────────────────────────
    def _handle(self, method: str, project_id: str, chunk: str, payload, result_q: queue.Queue):
        try:
            if method == "get":
                result = self._get(project_id, chunk)
            elif method == "update":
                result = self._update(project_id, chunk, payload)
            elif method == "add_from_catalog":
                result = self._add_from_catalog(project_id, chunk, payload)
            elif method == "add_manual":
                result = self._add_manual(project_id, chunk, payload)
            elif method == "trash_by_id":
                result = self._trash_by_id(project_id, chunk, payload)
            elif method == "list_projects":
                result = self._list_projects()
            elif method == "open_project":
                result = self._open_project(project_id)
            elif method == "create_project":
                result = self._create_project(payload)
            else:
                result = {"error": f"unknown_method:{method}"}
        except Exception as e:
            result = {"error": str(e)}
        result_q.put(result)

    def _find_window(self, project_id: str):
        for win in self.manager.windows:
            if win.project_id == project_id:
                return win
        return None

    # Only these keys from list_all_projects() are exposed over the API -
    # notably NOT project_path: callers never need filesystem locations.
    _PROJECT_LIST_KEYS = ("project_id", "display_name", "created_at", "last_modified", "status")

    def _list_projects(self) -> dict:
        from three_ps_lcca_gui.core.safechunk_engine import SafeChunkEngine
        open_ids = {w.project_id for w in self.manager.windows if w.project_id}
        projects = []
        for p in SafeChunkEngine.list_all_projects():
            entry = {k: p.get(k) for k in self._PROJECT_LIST_KEYS}
            # "status": "locked" just means a .lock file exists - which is
            # also true for projects open in THIS app instance, so surface an
            # explicit open flag for clarity.
            entry["open"] = p.get("project_id") in open_ids
            projects.append(entry)
        return {"ok": True, "projects": projects}

    def _open_project(self, project_id: str) -> dict:
        if self.manager.is_project_open(project_id):
            self.manager.open_project(project_id)  # focuses the existing window
            return {"ok": True, "status": "already_open"}

        from three_ps_lcca_gui.core.safechunk_engine import SafeChunkEngine
        if not SafeChunkEngine.get_project_info(project_id):
            return {"error": "project_not_found"}

        # open_project() schedules the heavy load on the event loop and
        # returns immediately - the project is NOT yet reachable when this
        # response goes out. Callers should poll GET /<id>/<page> until it
        # stops returning project_not_open.
        self.manager.open_project(project_id)
        return {"ok": True, "status": "opening"}

    def _create_project(self, payload) -> dict:
        # Currency is derived from the country (same as the New Project
        # dialog, where the currency combo is auto-filled and disabled) -
        # the caller never supplies it.
        from three_ps_lcca_gui.gui.components.utils.countries_data import COUNTRY_TO_CURRENCY

        display_name = payload["project_name"]
        country = payload["country"]
        unit_system = payload.get("unit_system", "metric")

        currency = COUNTRY_TO_CURRENCY.get(country)
        if not currency:
            return {"error": "no_currency_for_country"}

        project_id = self.manager.create_project(
            display_name, country, currency, unit_system
        )
        if project_id is None:
            return {"error": "creation_failed"}
        return {"ok": True, "project_id": project_id, "currency": currency}

    def _get(self, project_id: str, chunk: str) -> dict:
        win = self._find_window(project_id)
        if win is None:
            return {"error": "project_not_open"}
        data = win.controller.get_chunk(chunk)

        entry = CHUNK_PAGE_MAP.get(chunk)
        redact_hook = entry.get("redact_response") if entry else None
        if redact_hook:
            data = redact_hook(data)
        return {"ok": True, "data": data}

    def _update(self, project_id: str, chunk: str, payload) -> dict:
        win = self._find_window(project_id)
        if win is None:
            return {"error": "project_not_open"}
        if not isinstance(payload, dict):
            return {"error": "invalid_payload"}

        entry = CHUNK_PAGE_MAP.get(chunk)
        if entry and entry.get("read_only"):
            return {"error": "read_only_chunk"}

        page_name = entry["page_name"] if entry else None
        widget = win.widget_map.get(page_name) if page_name else None

        # Tier C pages (refresh_via_signal) have no load_data_dict - the API
        # never drives their widgets. Everything goes through the controller
        # and the page repaints itself off controller.chunk_updated.
        via_signal = bool(entry and entry.get("refresh_via_signal"))
        use_widget = widget is not None and not via_signal

        current = widget.get_data_dict() if use_widget else win.controller.get_chunk(chunk)

        # Hooks needing the stored data (e.g. entry-granular validation
        # against existing component/entry ids) run here, on the main thread,
        # where `current` is authoritative - the server-side pre-check ran
        # with current=None and could only catch structural problems.
        validate_hook = entry.get("validate_payload") if entry else None
        if validate_hook is not None:
            errors = validate_hook(payload, current)
            if errors:
                return {"error": "invalid_field_values", "details": errors}

        # Merge (PATCH-like): only keys present in the payload override the
        # current value - anything omitted keeps whatever is already stored.
        # Chunks with nested data register a merge_payload hook so a POST
        # can't clobber whole components/entries it didn't mention.
        merge_hook = entry.get("merge_payload") if entry else None
        merged = merge_hook(current, payload) if merge_hook else {**current, **payload}
        merged, skipped_locked = self._pin_locked_fields(entry, current, merged)

        if use_widget:
            widget.load_data_dict(merged)
            saved = widget.get_data_dict()
            validation = widget.validate() if hasattr(widget, "validate") else None
        else:
            saved = merged
            validation = None

        win.controller.save_chunk_data(chunk, saved)
        # save_chunk_data emits chunk_updated, which pre-existing listeners
        # (e.g. Recycling, for str_* chunks) react to on their own - untouched
        # here. For pages with a refresh_widget hook, explicitly repaint the
        # already-open widget to reflect this write. This call happens ONLY
        # as a direct result of an API write, never as a side effect of the
        # GUI's own native actions (which already update their own UI) - so
        # it can never double-render against a native action's own patch.
        # Skipped entirely if the page was never opened - nothing to repaint,
        # and it'll load correctly, fresh, whenever it next is.
        refresh_hook = entry.get("refresh_widget") if entry else None
        if refresh_hook is not None:
            page_widget = win.widget_map.get(page_name)
            if page_widget is not None:
                refresh_hook(page_widget, chunk)

        # redact_response strips server-owned bookkeeping (e.g. entry "meta")
        # from what the caller sees - `saved` (full fidelity, incl. meta) is
        # already persisted above, so this only affects the HTTP response.
        redact_hook = entry.get("redact_response") if entry else None
        response_data = redact_hook(saved) if redact_hook else saved

        result = {"ok": True, "data": response_data, "validation": validation}
        if skipped_locked:
            result["locked_fields_skipped"] = skipped_locked
            result["warning"] = (
                f"These fields are locked and cannot be changed via the API - "
                f"their current value was kept: {', '.join(skipped_locked)}"
            )
        return result

    def _add_from_catalog(self, project_id: str, chunk: str, payload) -> dict:
        """Powers POST /{project_id}/{chunk}/add_from_catalog - a single-
        material 'search the catalog by exact name and add it' shortcut,
        separate from the generic entry-patch update path. Only chunks that
        register an `add_from_catalog` hook support this."""
        return self._run_create_hook(project_id, chunk, payload, "add_from_catalog")

    def _add_manual(self, project_id: str, chunk: str, payload) -> dict:
        """Powers POST /{project_id}/{chunk}/add_manual - a single-material
        'give me the values directly, flat body, no catalog lookup'
        shortcut. Only chunks that register an `add_manual` hook support
        this."""
        return self._run_create_hook(project_id, chunk, payload, "add_manual")

    def _run_create_hook(self, project_id: str, chunk: str, payload, hook_name: str) -> dict:
        """Shared plumbing for the single-material 'shortcut' create
        endpoints (add_from_catalog, add_manual) - both hooks share the
        same (current, payload, registry, chunk) -> (merged, registry_patch,
        warning, errors) signature, so everything around calling the hook
        (find window, persist, keep the registry cache in sync, refresh the
        GUI, redact the response) is identical; only the hook itself
        differs in how it builds the new entry."""
        win = self._find_window(project_id)
        if win is None:
            return {"error": "project_not_open"}
        if not isinstance(payload, dict):
            return {"error": "invalid_payload"}

        entry = CHUNK_PAGE_MAP.get(chunk)
        hook = entry.get(hook_name) if entry else None
        if hook is None:
            return {"error": "not_supported"}

        current = win.controller.get_chunk(chunk)
        registry = win.controller.engine.fetch_chunk("str_component_registry") or {}
        merged, registry_patch, warning, errors = hook(current, payload, registry, chunk)
        if errors:
            return {"error": "invalid_field_values", "details": errors}

        win.controller.save_chunk_data(chunk, merged)
        if registry_patch is not None:
            # Mirrors the GUI's own manager.py _save_registry(): a direct
            # engine write, no chunk_updated emission - the registry chunk
            # has no dedicated tab refresh of its own, and the target
            # chunk's save_chunk_data above already covers what needs to
            # repaint (the new component's section renders off this chunk's
            # own data, not off the registry chunk's signal).
            # controller.get_chunk() serves from _chunk_cache once a chunk's
            # been read once (e.g. warmed at project load) - writing via
            # engine.stage_update() alone would leave that cache stale, so a
            # subsequent GET /str_component_registry would show the old
            # data even though the write succeeded. Patch the cache directly
            # too (same as what save_chunk_data does internally), without
            # its chunk_updated emission.
            win.controller.engine.stage_update(chunk_name="str_component_registry", data=registry_patch)
            win.controller._chunk_cache["str_component_registry"] = registry_patch

        refresh_hook = entry.get("refresh_widget")
        if refresh_hook is not None:
            page_widget = win.widget_map.get(entry["page_name"])
            if page_widget is not None:
                refresh_hook(page_widget, chunk)

        redact_hook = entry.get("redact_response")
        response_data = redact_hook(merged) if redact_hook else merged

        result = {"ok": True, "data": response_data}
        if warning:
            result["warning"] = warning
        return result

    def _trash_by_id(self, project_id: str, chunk: str, payload) -> dict:
        """Powers POST /{project_id}/{chunk}/trash - trashes one entry
        addressed by id alone. Only chunks that register a `trash_by_id`
        hook support this."""
        win = self._find_window(project_id)
        if win is None:
            return {"error": "project_not_open"}
        if not isinstance(payload, dict):
            return {"error": "invalid_payload"}

        entry = CHUNK_PAGE_MAP.get(chunk)
        hook = entry.get("trash_by_id") if entry else None
        if hook is None:
            return {"error": "not_supported"}

        current = win.controller.get_chunk(chunk)
        merged, errors = hook(current, payload)
        if errors:
            return {"error": "invalid_field_values", "details": errors}

        win.controller.save_chunk_data(chunk, merged)

        refresh_hook = entry.get("refresh_widget")
        if refresh_hook is not None:
            page_widget = win.widget_map.get(entry["page_name"])
            if page_widget is not None:
                refresh_hook(page_widget, chunk)

        redact_hook = entry.get("redact_response")
        response_data = redact_hook(merged) if redact_hook else merged
        return {"ok": True, "data": response_data}

    @staticmethod
    def _pin_locked_fields(entry, current: dict, merged: dict) -> tuple[dict, list[str]]:
        """Forces any field marked `_LOCKED` on the page widget to keep its
        current value, ignoring whatever the caller sent for it - mirrors the
        GUI, where those fields are disabled and never user-editable. Returns
        the corrected dict plus the list of locked keys where the caller's
        request would actually have changed something (so the caller can be
        warned, rather than the change silently vanishing)."""
        locked_keys = getattr(entry["widget_cls"], "_LOCKED", None) if entry else None
        if not locked_keys:
            return merged, []

        merged = dict(merged)
        skipped = []
        for key in locked_keys:
            if key in merged and merged[key] != current.get(key):
                skipped.append(key)
            if key in current:
                merged[key] = current[key]
            else:
                merged.pop(key, None)
        return merged, skipped
