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
            elif method == "get_tokens":
                result = self._get_tokens(project_id)
            elif method == "validate_all":
                result = self._validate_all(project_id)
            else:
                result = {"error": f"unknown_method:{method}"}
        except Exception as e:
            result = {"error": str(e)}
        result_q.put(result)

    def _get_tokens(self, project_id: str) -> dict:
        win = self._find_window(project_id)
        if win is None:
            return {"error": "project_not_open"}

        from three_ps_lcca_gui.gui.api import tokens

        # One-time token delivery defense: once handed out over HTTP once,
        # every later call is rejected outright - no popup shown.
        if tokens.is_delivered(project_id):
            return {
                "error": "token_already_delivered",
                "message": (
                    "The API token was already delivered once for this project. "
                    "Open File -> API Access in the app to view and copy the token."
                ),
            }

        # Anti-flood: caps how many times a script can make this dialog pop
        # up in one session, without any lingering "denied forever" state -
        # denying just fails this one request; the next ask still prompts,
        # up to the cap.
        if not tokens.can_prompt(project_id):
            return {
                "error": "too_many_requests",
                "message": (
                    "Too many API access requests for this project this session. "
                    "Use File -> API Access in the app to grant access manually."
                ),
            }

        # A minimized/background project window would otherwise leave its
        # modal child dialog effectively invisible - restore and raise it
        # before showing the prompt so there's actually something on
        # screen for the user to click.
        if win.isMinimized():
            win.showNormal()
        win.raise_()
        win.activateWindow()

        from three_ps_lcca_gui.gui.components.api_access_prompt import ApiAccessPrompt
        display_name = win.controller.active_display_name or project_id
        dlg = ApiAccessPrompt(display_name, parent=win)
        dlg.exec()

        if dlg.result_allowed:
            token = tokens.ensure_token(project_id)
            tokens.mark_delivered(project_id)
            return {"ok": True, "token": token}
        else:
            return {
                "error": "denied",
                "message": (
                    "API access was denied for this request. If this was a "
                    "mistake, open File -> API Access in the app to get the "
                    "key manually."
                ),
            }

    def _validate_all(self, project_id: str) -> dict:
        """Powers GET /{project_id}/validate - actually operates the
        Results page's "Calculate" button (ProjectWindow._run_calculate(),
        the exact slot self.btn_calculate.clicked is wired to), not a
        reimplementation of it, so the open GUI window's Results page
        updates exactly like a native click would: an error/warning report
        if anything's wrong, or a success indicator plus the real
        calculation (OutputsPage.run_calculation() launches that on its own
        QThread and returns immediately - non-blocking, so this call itself
        stays fast; the Results view then updates itself asynchronously off
        _on_calc_finished() same as always) if the project is clean, and
        either way the visible content_stack navigates to the Results page
        and the sidebar selection follows, same as a human click.

        _run_calculate() itself returns nothing (it's a GUI slot, not a
        query) - the errors/warnings this route's JSON response needs are
        computed here via the same per-page validate() aggregation
        OutputsPage.run_validation() uses internally, run BEFORE calling
        _run_calculate() so this response reflects the exact state that
        real call is about to (re-)validate. validate() is a pure read of
        already-current in-memory field state (no engine write, no dialog),
        so computing it here first and letting _run_calculate() compute the
        identical thing again internally is redundant but harmless - not a
        race, since both run synchronously on this same main-thread call."""
        win = self._find_window(project_id)
        if win is None:
            return {"error": "project_not_open"}

        from three_ps_lcca_gui.gui.components.utils.form_builder.form_definitions import ValidationStatus

        for name in win._page_names:
            win._get_or_create_widget(name)
        win.outputs_page.register_pages(win.widget_map)

        all_errors: dict = {}
        all_warnings: dict = {}
        for name, page in win.outputs_page._pages.items():
            res = page.validate()
            if isinstance(res, dict):
                if res.get("errors"):
                    all_errors[name] = res["errors"]
                if res.get("warnings"):
                    all_warnings[name] = res["warnings"]
            else:
                status, issues = res
                if status == ValidationStatus.ERROR:
                    all_errors[name] = issues
                elif status == ValidationStatus.WARNING:
                    all_warnings[name] = issues

        # The real button handler - updates the open window's Results page
        # (error/warning report, or success + async calculation) exactly
        # like a native click, and navigates the visible window there.
        win._run_calculate()

        # Maps each page name in errors/warnings to the chunk id(s) an API
        # caller would GET/POST to actually fix something on that page - a
        # page name alone (e.g. "Carbon Emissions Data") isn't directly
        # callable, and one page can span several chunks (that one spans
        # five: social_cost_data, machinery_emissions_data, etc.). Built
        # from the same registry every other endpoint is generic over, so
        # it never goes stale as pages/chunks are added.
        page_chunks: dict[str, list[str]] = {}
        for chunk_name, entry in CHUNK_PAGE_MAP.items():
            page_chunks.setdefault(entry["page_name"], []).append(chunk_name)
        for chunk_list in page_chunks.values():
            chunk_list.sort()

        return {
            "ok": True,
            "valid": not all_errors,
            "errors": all_errors,
            "warnings": all_warnings,
            "page_chunks": {name: page_chunks.get(name, []) for name in set(all_errors) | set(all_warnings)},
        }

    def _find_window(self, project_id: str):
        """Every bridge method resolves its target window through here first
        - the one place to fix a real bug this API's own testing surfaced:
        gui/components/utils/common_requested_data.py backs get_currency() /
        get_project_iso3() / etc. with a single process-wide "active
        controller" global, set only once per window at creation
        (ProjectManager._create_window()) and never updated when a
        different, already-open window is what's actually being acted on.
        With 2+ project windows open, any of those helpers could silently
        return a DIFFERENT project's data than the one this request targets
        (confirmed live: gui/api/pages/carbon_emission.py's iso3 auto-lock
        and currency lookup would read the wrong project's country/currency).
        Re-syncing the global to this request's own window/controller here -
        the one place every bridge method already resolves it - fixes every
        current and future page's use of those helpers for anything reached
        through the API, without touching the registry/hook contract or any
        individual page. Safe without locking: Qt delivers this signal's
        queued connection (see __init__'s Qt.QueuedConnection) one at a time
        on the main thread, and bridge.call() blocks its caller until this
        whole handler returns, so no second request's window can be
        resolved (and re-sync this same global) while this one is still
        using it.

        This does NOT fix the same bug for purely GUI-driven reads (e.g. a
        user manually clicking between multiple open project windows with
        no API involved) - that still needs a fix on the GUI side (e.g.
        ProjectWindow re-asserting itself as the active controller on
        focus/show), tracked separately.
        """
        for win in self.manager.windows:
            if win.project_id == project_id:
                from three_ps_lcca_gui.gui.components.utils.common_requested_data import set_controller
                set_controller(win.controller)
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
