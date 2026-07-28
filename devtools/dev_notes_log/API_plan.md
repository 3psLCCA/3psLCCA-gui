# Local HTTP API — full-app rollout plan (per GUI page)

## Context

The app exposes a local HTTP API (`http://127.0.0.1:8765/<project_id>/<chunk>`) so an
external tool, script, or LLM agent can read and update an open project's data live in
the running GUI. Phase 1 (Bridge Data pilot + General Information) is **implemented and
working**. This document records the architecture as actually built, then gives the
implementation plan for every remaining GUI page.

## Status

| Page (sidebar name)       | Widget class          | Chunk(s)                     | API status |
|---------------------------|-----------------------|------------------------------|------------|
| General Information       | `GeneralInfo`         | `general_info`               | ✅ done |
| Bridge Data               | `BridgeData`          | `bridge_data`                | ✅ done |
| Financial Data            | `FinancialData`       | `financial_data`             | ✅ done |
| Maintenance and Repair    | `Maintenance`         | `maintenance_data`           | ✅ done |
| Demolition                | `Demolition`          | `demolition_data`            | ✅ done |
| Traffic Data              | `TrafficData`         | `traffic_and_road_data`      | planned — Tier B |
| Construction Works Data   | `StructureTabView`    | `str_super_structure`, `str_sub_structure`, `str_foundation`, `str_misc` (read-only: `str_component_registry`; internal: `str_summary`) | ✅ done (Tier C) |
| Carbon Emissions Data     | `CarbonEmissionTabView` | `transport_emissions_data`, `machinery_emissions_data`, `diversion_emissions`, `social_cost_data` (internal: `transport_data`; `material_emissions_data` **not exposed** — see note below) | planned — Tier C |
| Recycling                 | `Recycling`           | **no API of its own** — controlled entirely via `str_*` entry writes (see note below) | — |
| Results                   | `OutputsPage`         | `outputs_data`               | planned — Tier D (read-only) |
| *(app-level)* Material catalog search | — (`MaterialSearchEngine`, no widget) | — (reads SOR JSON databases, not chunks) | ✅ done (Tier E, read-only, no Qt) |
| *(app-level)* Project lifecycle | — (`ProjectManager` / `SafeChunkEngine` statics) | — (list/create/open/close projects) | ✅ done (Tier E — list/active/open/new; close and delete not exposed) |

Tiers: **A** = registration-only (FieldDef form, copy the existing pattern).
**B** = FieldDef form plus nested/custom data needing schema + validator hooks.
**C** = table/tab pages with no `load_data_dict()`; API writes via controller, GUI
refreshes via signal. **D** = read-only chunk. **E** = app-level read-only service
endpoints (not chunk-addressed).

## Architecture as built (recap)

- `gui/api/server.py` — Flask on a daemon thread (`make_server`), generic routes
  `GET`/`POST /<project_id>/<chunk>`. GET returns data **and** field schema
  (self-describing); 404s carry a usage blurb + `available_pages`.
- `gui/api/bridge.py` — `ApiBridge(QObject)`: Flask worker thread → Qt main thread
  via queued Signal + reply `queue.Queue`. All widget/controller access happens on the
  main thread. POST semantics are **merge (PATCH)**: only sent keys change; locked
  fields (`_LOCKED` on the widget class) are pinned with a warning in the response.
- `gui/api/registry.py` — `CHUNK_PAGE_MAP` + `register_chunk()`,
  `describe_chunk_fields()`, `validate_payload_keys()` (pure, no Qt).
- `gui/api/pages/` — one module per page; registers at import time.
- `gui/api/tokens.py` — per-project in-memory bearer tokens (`X-API-Token`).
- `gui/api/image_upload.py` — `upload_img` fields accept base64 or an http(s) URL.
- UI: File → API Access dialog; Settings → "Enable local API server".

## Prerequisite: registry extensions (one-time, before Tiers B–D)

The current `register_chunk()` assumes a flat FieldDef form driving a
`ScrollableForm` widget. The remaining pages break one or both assumptions, so extend
the registry entry — **generic engine stays generic; nothing page-specific lands in
server.py/bridge.py**:

1. **Optional `field_defs`** — allow `field_defs=None` plus a hand-written
   `schema: dict` (JSON-Schema-ish) for table/nested chunks. `describe_chunk_fields()`
   returns whichever the entry has.
2. **Per-entry hooks** — optional callables, all pure (no Qt), run where
   `validate_payload_keys()` runs today:
   - `validate_payload(payload, current) -> list[str]` — custom validation for
     nested/tabular data.
   - `merge_payload(current, payload) -> dict` — custom merge for chunks where
     top-level `{**current, **payload}` would clobber nested dicts (e.g. traffic's
     `vehicle_data`). Default stays the top-level merge.
3. **`read_only=True`** flag — POST returns `405 read_only_chunk`. Needed for
   `outputs_data` and the internal `str_component_registry` / `str_summary` /
   `transport_data` chunks if we expose them.
4. **Signal-based GUI refresh for non-form pages** — Tier C widgets have no
   `load_data_dict()`. Instead of driving widgets, `bridge._update()` for entries with
   `refresh_via_signal=True` writes via `win.controller.save_chunk_data(chunk, merged)`
   and lets the page repaint itself off `controller.chunk_updated`. Precedents already
   in the codebase: `Recycling` connects `chunk_updated` → `on_refresh` for the
   `str_*` chunks (recycling/main.py ~413), and `StructureTabView` has
   `refresh_tab_by_chunk(chunk_id)` (structure/main.py ~189). Each Tier C page only
   needs its existing refresh hook connected to `chunk_updated`.

> Note: the architecture review (2026-07) recommends eventually routing **all** pages
> through path 4 (API → controller → engine, widgets as observers) so behavior stops
> depending on whether a page has been opened. Tier A/B below keeps the current
> widget-driven path to minimize churn; migrating them to the observer path is a
> follow-up, not a blocker.

---

## Per-page implementation plans

### Tier A — registration-only forms

These three are `ScrollableForm` subclasses with module-level FieldDef lists, standard
`get_data_dict()`/`load_data_dict()`/`validate()`. Identical to the Bridge Data
pattern; **no engine changes, no widget changes**.

#### 1. Financial Data (`financial_data`)

- New file `gui/api/pages/financial_data.py`:
  ```python
  from three_ps_lcca_gui.gui.components.financial_data.main import (
      FINANCIAL_FIELDS, FINANCIAL_WARN_RULES, FinancialData,
  )
  from ..registry import register_chunk

  register_chunk(
      "financial_data",
      page_name="Financial Data",
      widget_cls=FinancialData,
      field_defs=FINANCIAL_FIELDS,
      warn_rules=FINANCIAL_WARN_RULES,
  )
  ```
- Add `from . import financial_data` to `pages/__init__.py`. Done.

#### 2. Demolition (`demolition_data`)

- New file `gui/api/pages/demolition.py` registering `DEMOLITION_FIELDS` +
  `DEMOLITION_WARN_RULES`, `widget_cls=Demolition`, `page_name="Demolition"`.
- Same two-line wiring. Done.

#### 3. Maintenance and Repair (`maintenance_data`)

- New file `gui/api/pages/maintenance.py` registering `MAINTENANCE_FIELDS`,
  `widget_cls=Maintenance`, `page_name="Maintenance and Repair"` (no warn-rules dict —
  omit).
- **Bonus (optional, small)**: the page has `load_suggested_values()` and
  `clear_all()` buttons. When the command surface lands (see review), expose them as
  `POST .../maintenance_data/commands/load_suggested` — for now, callers can read
  `SUGGESTED_VALUES` via a normal POST of those values, so nothing blocks.

**Verification (per page):** `GET` returns data + schema; `POST` one field → widget
updates live if the page is open; invalid combo/range value → `400
invalid_field_values`; re-GET reflects the merge.

### Tier B — form pages with nested data

#### 4. Traffic Data (`traffic_and_road_data`)

The page is a `ScrollableForm` (flat FieldDefs from `TRAFFIC_FIELDS`,
`OUTSIDE_INDIA_FIELDS`, `PROJECT_MODE_FIELDS`) **plus** nested structures produced by
`collect_data()` (traffic_data/main.py ~953): `vehicle_data` (per-vehicle dict, merged
against the stored chunk to preserve extra keys), `peak_hour_distribution`,
`global_entry`, `wpi` (profile id + snapshot + custom profiles), `mode`, `remarks`
(HTML), `force_free_flow_off_peak`. It overrides `get_data_dict`/`load_data_dict` to
route through `collect_data()`/`load_data()`, so the existing widget-driven update
path **works as-is** — the work is schema + validation, not plumbing:

- New file `gui/api/pages/traffic_data.py`:
  - Register with `field_defs=` the concatenated FieldDef lists (they describe the
    flat keys) **and** a supplementary `schema` block describing the nested keys
    (`vehicle_data`: map of vehicle-key → `{count, growth_rate, ...}` rows;
    `peak_hour_distribution`: map of hour-band → percentages; `global_entry`;
    `wpi`). Mark `wpi.data_snapshot` and `wpi.custom_profiles` as
    "server-computed — send `selected_profile_id` only" in the schema description so
    agents don't try to fabricate snapshots.
  - `validate_payload(payload, current)` hook: type-check the nested dicts (row keys
    exist, values numeric, severity percentages sum ≤ 100), reject unknown top-level
    keys exactly like the flat validator does.
  - `merge_payload` hook: deep-merge `vehicle_data` / `peak_hour_distribution` /
    `global_entry` per-key instead of top-level replace (mirrors what
    `collect_data()` itself does with `existing_veh`).
- No changes to `traffic_data/main.py`.
- Verification: POST a single vehicle's count → only that vehicle row changes; POST
  `mode` → the form switches field sets live; invalid severity split → 400.

### Tier C — table/tab pages (API writes via controller; GUI refreshes via signal)

Common mechanics for all three (uses prerequisite items 1, 2, 4):

- Entries register with `field_defs=None`, a hand-written `schema`,
  `refresh_via_signal=True`, and custom `validate_payload`/`merge_payload`.
- `bridge._update()` path: merge → validate → `win.controller.save_chunk_data(chunk,
  merged)` → return saved data. The page widget repaints from the
  `chunk_updated` signal; the API never touches these widgets.

#### 5. Construction Works Data (`str_super_structure`, `str_sub_structure`, `str_foundation`, `str_misc`)

- Data shape (all four chunks identical): `{component_name: {"values": {...}, items:
  [...]}}` — component groups with material/work-item rows (`name`, `unit`, `rate`,
  quantities; the Excel importer's `REQUIRED_FIELDS`/`NUMERIC_FIELDS` in
  `excel_importer.py` are the de-facto row schema).
- New file `gui/api/pages/structure.py` registering **each of the four chunks**
  separately (the API stays chunk-addressed; one registration per chunk, one shared
  schema/validator/merge implementation).

**Reuse the material-entry logic from `structure/widgets/material_dialog.py` — do
not reimplement it.** That module already contains the canonical add/modify
pipeline; the API must produce entries indistinguishable from GUI-added ones:

- `convert_sor_item_to_material(dict_b)` — pure Python; converts a raw SOR/catalog
  item into the full `{id, values, meta, state}` entry (UUID, `db_original`
  snapshot, `defaults`, carbon-eligibility, custom-vs-internal source tagging).
  **This is the API's add-from-catalog path**: the caller sends a search result (or
  `db_key` + `name`/`src_id` for the server to look up) plus `quantity`, and the
  entry is built by this function — never hand-assembled.
- `_validate_item()` / `_REQUIRED_ITEM_KEYS` / `_ITEM_DEFAULTS` — row schema check
  and defaults; reuse in the payload validator.
- The validation rules in `MaterialDialog.validate_and_accept()` (name/unit
  required, quantity > 0, rate required and ≥ 0, carbon EF/CF checks, unit-dimension
  mismatch, recovery % ≤ 100) are the authoritative material rules but are
  interwoven with `QMessageBox` confirms. **Refactor**: extract them into a pure
  `validate_material_values(values) -> {errors, warnings}` that the dialog and the
  API validator both call — dialog keeps its interactive "Continue?" prompts for
  warnings; the API returns warnings in the response (hard errors → 400).
- `MaterialDialog._compute_action()` + `get_values()` define the source-lineage
  rules (`db` → `db_modified` when values change, `custom_db` →
  `custom_db_modified`, else `user_added`/`manual`; `db_original` snapshot always
  preserved). **Refactor**: extract a pure
  `compute_source_transition(meta, values_changed) -> source` used by both the
  dialog and the API's modify path, so API edits keep the same audit lineage
  Carbon/Recycling/exports rely on.
- **File split (small)**: these pure functions currently live inside the Qt module
  (`material_dialog.py` imports PySide6 at module level). Move them to a Qt-free
  `structure/registry/material_entry.py`; `material_dialog.py` re-imports from
  there. Same pattern as the Tier-A `fields.py` splits, and required anyway for
  headless mode.

Because materials are `{id, values, meta, state}` entries (not flat rows), writes
are **entry-granular, not raw-chunk-granular** — a raw chunk POST would let callers
bypass id/meta/defaults bookkeeping:

  - `validate_payload`: each entry validated via `validate_material_values`;
    reject entries referencing unknown component names/UUIDs rather than silently
    creating registry orphans; reject direct mutation of `meta`/`id` (server-owned).
  - `merge_payload`: merge at component → entry(id) level — sent entries
    upsert by `id` (add-from-catalog/manual creates the entry server-side first);
    omitted components/entries untouched; `state.in_trash` toggling allowed
    (mirrors the GUI's trash tab) rather than hard row deletion.

**This write path is also the sole API surface for carbon-emission and
recyclability data** (see the notes in the Carbon and Recycling sections below —
neither gets an API of its own). The per-entry rules the Material Emissions and
Recycling pages enforce move into this path's validator/apply step, mirroring the
widgets exactly:

  - Setting any carbon field (`values.carbon_emission` / `carbon_unit` /
    `conversion_factor` / `carbon_emission_src`) also sets
    `state.carbon_conversion_confirmed = true`, stamps `meta.modified_on`, and
    clears `values.exclusion_reason.carbon` — same as
    `MaterialEmissions._open_emission_edit()`.
  - Toggling `state.included_in_carbon_emission` follows `_toggle_inclusion()`:
    re-including an entry whose unit conversion is suspicious
    (`analyze_conversion_sympy`) and unconfirmed → 400 with the fix spelled out
    (POST corrected emission fields first).
  - Toggling `state.included_in_recyclability` and setting `values.scrap_rate` /
    `values.post_demolition_recovery_percentage` (recovery ≤ 100) follows the
    Recycling page's rules, including writing `exclusion_reason.recycling`
    server-side (factor the existing logic in `recycling/main.py` ~731-827 into a
    module-level function both the widget and this path call).
  - `values.exclusion_reason.*` is server-owned/derived — never caller-writable.
  - The pure helpers these rules need — `is_carbon_valid()`, `calc_carbon()`,
    `_cf_value()` (top of material_emissions.py, already Qt-free) and
    `analyze_conversion_sympy()` (unit_resolver) — move to a Qt-free
    `carbon_emission/emissions_calc.py`.
- GUI refresh: connect `controller.chunk_updated` → `refresh_tab_by_chunk(chunk)` in
  `StructureTabView.__init__` (one line; the method already exists).
- `str_component_registry` and `str_summary` are **derived/bookkeeping chunks** — do
  not accept writes. Either leave unregistered (404) or register `read_only=True` so
  agents can inspect them. Registry consistency is why row-level validation above
  matters.
- Verification: POST a rate change to one item → table cell updates live, totals
  (`str_summary`) recompute on next page interaction; GET `str_summary` (if
  registered) reflects it.

#### 6. Carbon Emissions Data (five sub-chunks)

Each tab of `CarbonEmissionTabView` owns its own chunk; register each individually in
`gui/api/pages/carbon_emission.py`:

| Chunk | Tab widget | Shape / notes |
|---|---|---|
| `diversion_emissions` | `TrafficEmissions` | Standard BaseDataWidget with `DIRECT_FIELDS` FieldDefs → register like Tier A but `page_name` resolution goes through the tab view — use `refresh_via_signal` path instead. |
| `social_cost_data` | `SCCWidget` | Small form (`_SELECTOR_FIELDS`) + SCC database selection; register FieldDefs; `refresh_via_signal`. |
| `machinery_emissions_data` | `MachineryEmissions` | `LUMPSUM_ELEC_FIELDS`/`LUMPSUM_FUEL_FIELDS` FieldDefs + per-machine table → FieldDefs plus a `schema` block for the table; custom validator/merge. |
| `transport_emissions_data` | `TransportEmissions` | Table of transport legs; hand-written `schema`; custom validator/merge. It also stages the internal `transport_data` chunk — that one stays unregistered or `read_only`. |
| `material_emissions_data` | `MaterialEmissions` | **Not exposed** — derived view over `str_*` entries; see decision note below. |

**Material emissions: no API — decision.** `material_emissions_data` holds no
editable data (`MaterialEmissions.get_data()` stores only a derived summary
computed from the four `str_*` chunks; the editable carbon fields live on the
material entries). The page is a view with edit buttons over Construction Works
data, so it gets **no API registration at all** — everything it controls is done
through the `str_*` entry write path (see the carbon/recyclability rules in Tier C
item 5). An agent that wants totals can compute them from the `str_*` entries it
already reads, or read `outputs_data` (Tier D). Validators needing cross-chunk
reads (component refs in `str_component_registry`) use the
`validate_in_context(payload, controller)` hook (runs in the bridge handler where
controller access is legal, not in the pure validator).

- GUI refresh: `CarbonEmissionTabView` gets a `chunk_updated` → refresh-matching-tab
  connection (same one-liner pattern as structure; sub-widgets already have
  `refresh_from_engine`).
- Verification: POST to `social_cost_data` with the Carbon page open on another tab →
  switching to the SCC tab shows the new values; POST an invalid field value → 400.

#### 7. Recycling — no API (decision)

Same reasoning as material emissions: the Recycling page is a decision table over
the structure components — the editable state (`state.included_in_recyclability`,
`values.scrap_rate`, `values.post_demolition_recovery_percentage`, and the
`exclusion_reason.recycling` write-back into `str_*` chunks, recycling/main.py
~731-827) all lives on `str_*` material entries. It gets **no chunk registration**;
callers control recyclability entirely through the `str_*` entry write path, whose
validator/apply step carries the Recycling page's rules (see Tier C item 5). The
page's own `recycling_data` chunk stays unregistered.

- GUI refresh still works with zero extra code: `Recycling.on_refresh` already
  listens to `chunk_updated` for the `str_*` chunks, which is exactly where API
  writes land.
- Verification: POST `{"state": {"included_in_recyclability": false}}` for an entry
  → Recycling table updates live and the component shows the exclusion reason in
  Construction Works.

### Tier D — read-only

#### 8. Results (`outputs_data`)

- `OutputsPage` computes LCC summaries into `outputs_data` (outputs_page.py, `CHUNK =
  "outputs_data"`, state persisted via `fetch_chunk`).
- Register with `read_only=True` and a minimal hand-written `schema` describing the
  result structure. `GET` only; `POST` → `405 read_only_chunk` with a message telling
  the caller results are computed from the input chunks.
- This is the endpoint that makes the API genuinely useful to agents (change inputs →
  read outcomes), so do it **early** despite being listed last — it's tiny.
- Future (out of scope here): a `recompute` command so an agent can force a fresh
  calculation without opening the Results page.

### Tier E — app-level service endpoints

#### 9. Material catalog search (Construction Works support)

The Construction Works page's material picker is driven by
`structure/registry/search_engine.py` (`MaterialSearchEngine`) over the SOR databases
in `structure/registry/material_database/` (catalog: `material_catalog.py` —
`get_registry()`, `list_databases()`). This is the same lookup a user does via the
GUI's search dialog (`material_dialog.py`), and an LLM needs it for the core
workflow: **search catalog → pick entry (name/unit/rate) → POST it as a row into the
right `str_*` chunk**. Without it an agent has to invent rates.

Key properties that make this the easiest addition in the whole plan:

- `MaterialSearchEngine` is **pure Python — no Qt, no engine, no project window**.
  Endpoints run directly on the Flask worker thread; **no `ApiBridge.call()`**, no
  main-thread hop, no `project_not_open` case.
- It is read-only over static JSON databases → GET-only endpoints.

**New file `gui/api/catalog.py`** (route registration called from `_create_app()`),
endpoints all GET, all requiring a valid token (see auth note below):

| Endpoint | Backed by | Purpose |
|---|---|---|
| `GET /catalog/databases` | `_list_sor_options()` (material_dialog.py → material_entry.py) | Available SOR databases **including custom DBs** (`custom::` keys): `db_key`, region, label — the same list the GUI's picker shows. |
| `GET /catalog/categories?db_key=&region=` | `engine.list_categories()` | `{db_key: {sheet: [components]}}` — lets an agent learn the vocabulary before filtering. |
| `GET /catalog/components?category=` | `engine.list_components()` | Flat component list, optionally per category. |
| `GET /catalog/items?category=&component=&db_key=` | `engine.list_by_category()` | Full listing of one category/component. |
| `GET /catalog/search?q=steel+rebar&category=&component=&db_key=&region=&limit=&offset=` | `engine.search()` | Token-based full-text search (same matcher the GUI dialog uses, so API and GUI results never diverge). |

Implementation notes:

- **Engine lifecycle**: construct one `MaterialSearchEngine()` lazily on first
  catalog request and cache it module-level (it loads every OK database's JSON at
  construction — don't rebuild per request). Filtered variants (`db_key=`,
  `region=`) can be served from the cached all-DB instance by passing the filters to
  `search()`/`list_by_category()`, which already accept them — no extra instances
  needed.
- **Pagination**: `search` and `items` take `limit` (default 50) and `offset` —
  SOR sheets are large and an unbounded response blows out an LLM's context. The
  response includes `total` so the caller knows to page.
- **Response rows**: return entries exactly as `_iter_items()` yields them
  (`db_key`, `region`, `country`, `category`, `component`, `name`, `unit`, `rate`,
  `src_id`, carbon fields, …), filtered through `_validate_item()` (from
  `material_dialog.py` → moved to `material_entry.py`, see Tier C) so the API skips
  the same malformed rows the GUI dialog skips. The endpoint's usage text states the
  hand-off: pass a returned row (or its `db_key` + `src_id`) to the structure
  add-material path, where the server builds the full entry via
  `convert_sor_item_to_material()` — the caller never assembles `{id, values, meta,
  state}` by hand.
- **Auth**: catalog data is not project data, but the API stays closed — accept any
  currently-valid project token (add `tokens.check_any(provided)` helper). If no
  project is open there is no valid token, which is acceptable: the API's contract
  is already "only reachable while a project is open".
- **Discovery**: add the catalog endpoints to `_usage_info()` so 404 self-help
  mentions them; document in `api_usage_readme.md` with a worked example
  (search "steel rebar" → POST the chosen row into `str_super_structure`).
- **Custom units**: `CustomMaterialDB` (user-defined units/materials) is a separate
  source; out of scope for the first cut — note it as a follow-up endpoint
  (`GET /catalog/custom`) if agents need user-defined materials too.

Verification: `GET /catalog/search?q=steel+rebar` returns the same entries the GUI
dialog shows for that query; `limit=5` caps rows and reports `total`; missing token →
401; results paste directly into a `str_super_structure` POST that then appears in
the table.

#### 10. Project lifecycle endpoints (`/projects`)

Without these, an agent can only work on a project a human already opened by hand.
Routes (namespaced under `/projects` so they can't collide with
`/<project_id>/<chunk>`):

| Endpoint | Backed by | Notes |
|---|---|---|
| `GET /projects` | `SafeChunkEngine.list_all_projects()` | Static, Qt-free file scan — runs on the Flask thread, **no bridge call**. Add `open: true/false` per row via `manager.is_project_open()` (needs the bridge only if we want live window state; simpler: match against the token registry's open set). |
| `GET /projects/<id>` | `SafeChunkEngine.get_project_info()` | Static deep scan — Flask thread, no bridge. |
| `POST /projects` (create) | new `ProjectManager.create_project()` (see refactor below) | Body: `display_name` (required), `country`, `currency`, `unit_system` — validated against the same option lists `NewProjectDialog` uses (`countries_data`). Returns `project_id` + the project token. **Main-thread via `ApiBridge`** (it builds/loads a window in GUI mode). |
| `POST /projects/<id>/open` | `manager.open_project(project_id)` | Idempotent (already-open → focuses the window, still 200). Returns the project token so the agent can proceed to chunk calls. Main-thread via bridge. |
| `POST /projects/<id>/close` | `win.close()` on the matching window | Runs the existing `closeEvent` path (force-sync, token cleanup). Main-thread via bridge. |

**Required refactor — extract creation from the dialog callback.** The real creation
sequence currently lives inside `NewProjectDialog`'s `loading_started` handler in
`project_manager.py` (~94-144): generate `proj_<8hex>` → `controller.init_project()`
→ seed `general_info` (project_name + the three locked fields), `bridge_data`
(`project_country`), `str_component_registry` (`STRUCTURE_DEFAULTS`) → `force_sync()`
→ `record_open` + `ensure_token` → `_warm_cache`. Extract that into
`ProjectManager.create_project(display_name, country, currency, unit_system) ->
project_id`, called by both the dialog callback (which keeps its dialog/preload/show
choreography) and the API command. This is the only way an agent can ever set the
locked fields (`project_country`, `project_currency`, `unit_system`) — they are
create-time-only by design, so the create endpoint must accept them.

**Auth prerequisite — app-session token.** `GET /projects` and `POST /projects` must
work when *no* project is open, and today no token exists then. Add an app-session
token: generated once at server start (`tokens.ensure_app_token()`), shown in the API
Access dialog and Settings, valid for all `/projects*` and `/catalog/*` endpoints
(and accepted on project routes too). Per-project tokens keep working on
project-scoped routes; per-project **revoke** still cuts off a single project. This
resolves the `tokens.check_any()` stopgap from the catalog section — catalog
endpoints should just use the app token.

**Deliberately not exposed (for now):** `delete_project()` — destructive and
irreversible; an autonomous agent should not be able to trigger it. If it's ever
added, it must be opt-in via a setting, default off. `import_project` / copy / share
become candidates once implemented in the engine.

Verification: with the app freshly started and no project open, `GET /projects`
(app token) lists all projects with `open: false`; `POST /projects` creates one,
the window appears, `general_info` shows the locked country/currency; `POST
/projects/<id>/close` closes the window and subsequent chunk calls return
`project_not_open`.

---

## Rollout order

1. **Registry extensions** (prereq — optional field_defs, hooks, `read_only`,
   `refresh_via_signal`), with unit tests for the pure parts.
2. **Tier A**: `financial_data`, `demolition_data`, `maintenance_data` — three
   ~15-line files, immediate coverage win.
3. **Tier E**: app-session token first (auth prerequisite), then catalog search
   endpoints and project lifecycle (`/projects` list/info are pure; create needs the
   `ProjectManager.create_project()` extraction). Independent of the registry
   extensions; high agent value — after this step an agent can go from cold start to
   working on a project without a human opening anything.
4. **Tier D**: `outputs_data` read-only — small, high agent value.
5. **Tier B**: `traffic_and_road_data`.
6. **Tier C**: structure chunks (including the carbon/recyclability entry rules —
   that single write path covers Material Emissions and Recycling, which have no
   API of their own) → remaining carbon chunks (`diversion_emissions`,
   `social_cost_data`, `machinery_emissions_data`, `transport_emissions_data`).
   Ship Tier E before/with the structure chunks, since search → insert-row is the
   workflow that makes writable `str_*` chunks usable to an agent.

Each step is independently shippable; `api_usage_readme.md` gets its
`available_pages` list and any new schema conventions updated per step.

## Standing decisions (unchanged from phase 1)

- Flask + werkzeug daemon thread; queued-signal marshaling in `ApiBridge`; merge
  (PATCH) update semantics; per-project in-memory tokens via `X-API-Token`;
  locked-field pinning with response warning; self-describing GET; image fields
  accept base64 or URL; Settings toggle (restart to apply).
