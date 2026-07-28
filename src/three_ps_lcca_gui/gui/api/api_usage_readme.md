# Local GUI API

A local HTTP API for reading and updating an open project's data from an external
tool, script, or LLM/agent integration - live, in the running GUI. Auto-starts with
the app (toggle in **Settings → Local API**) and only reaches projects that are
currently open.

Routes are fully generic (`/<project_id>/<page>` works for whatever's registered).
Registered today: **Bridge Data** (`bridge_data`), **General Information**
(`general_info`), **Financial Data** (`financial_data`), **Maintenance and Repair**
(`maintenance_data`), **Demolition** (`demolition_data`), and the four
**Construction Works Data** table chunks - `str_foundation`, `str_sub_structure`,
`str_super_structure`, `str_misc` (plus the read-only `str_component_registry`).
Adding another page is a small, self-contained change - see
[Extending to more pages](#extending-to-more-pages). The examples in this doc use
`bridge_data`, but auth, locked fields, and error shapes work identically for every
registered page.

Two kinds of pages exist, distinguishable by what `GET` returns:

- **Form pages** (Bridge Data, General Information, Financial Data, Maintenance,
  Demolition) return a flat `"fields"` array and use top-level merge semantics -
  see [Update semantics](#update-semantics--merge).
- **Table pages** (the `str_*` Construction Works chunks) return a `"schema"` object
  instead, and use **entry-granular, single-entry** semantics (one component, one
  entry per `POST` - no bulk), since their data is `{component: [entry, ...]}`
  rather than flat key/value pairs - see
  [Construction Works Data](#construction-works-data-table-pages) below. The
  `str_component_registry` chunk is read-only (`GET` only; `POST` returns `405`).

---

## Table of Contents

- [Discovery - start here with zero prior context](#discovery--start-here-with-zero-prior-context)
- [Project management - list, open, create](#project-management--list-open-create)
- [Getting the URL and token](#getting-the-url-and-token)
- [Authentication](#authentication)
- [Endpoints](#endpoints)
  - [GET /\<project_id\>/bridge_data](#get-project_idbridge_data)
  - [POST /\<project_id\>/bridge_data](#post-project_idbridge_data)
- [Bridge Data fields](#bridge-data-fields)
- [Errors](#errors)
  - [Self-documenting 404s](#self-documenting-404s)
- [Update semantics - merge](#update-semantics--merge)
- [Construction Works Data (table pages)](#construction-works-data-table-pages)
  - [POST .../add_from_catalog](#post-project_idchunkadd_from_catalog)
  - [POST .../add_manual](#post-project_idchunkadd_manual)
  - [POST .../trash](#post-project_idchunktrash)
- [Material catalog search](#material-catalog-search)
- [Image upload fields](#image-upload-fields)
- [Disabling the API](#disabling-the-api)
- [Extending to more pages](#extending-to-more-pages)

---

## Discovery - start here with zero prior context

`GET /` and `GET /help` require **no token** and return full machine-readable
documentation: the URL pattern, the auth header name, how to get a token, every
registered page name, and behavior notes (merge semantics, locked fields, image
uploads, error shapes). This is the same convention GitHub, Stripe, and most REST
APIs use - the docs endpoint stays public even though the data endpoints require
auth, so a caller (an LLM/agent especially) can go from "I have a base URL and
nothing else" to a working request without ever reading source code:

```bash
curl http://127.0.0.1:8765/help
```

Every error response - including `401` - also carries a `documentation_url`
pointing back here, so there's no dead end: even a rejected request tells you
where to learn how to do it right (same pattern as GitHub API's
`documentation_url` field on error bodies). See [Errors](#errors) for exact
shapes.

---

## Project management - list, open, create

App-level endpoints, all **unauthenticated** - per-project tokens can't
gate them (a token only exists once its project is open), and they expose
nothing a local process couldn't already do: the list mirrors what's readable
on disk, and opening/creating only shows a window. Reading or writing project
*data* still requires the per-project token, which no endpoint ever returns.

### `GET /projects`

Lists every project on this machine: `project_id`, `display_name`, dates,
`status` (`ok`/`locked`/`crashed`/`corrupted`), and an `open` flag for whether
it's currently open in the app. Note `status: "locked"` is also true for
projects open in *this* app instance (they hold the lock) - `open` is the
authoritative "can I talk to it right now" signal.

```bash
curl http://127.0.0.1:8765/projects
```

### `GET /projects/active`

Same shape as `GET /projects`, but filtered to only the projects **currently
open in the app** - i.e. the ones a data request can actually reach right now.
Also returns a `count`.

```bash
curl http://127.0.0.1:8765/projects/active
```

### `POST /projects/open`

```bash
curl -X POST http://127.0.0.1:8765/projects/open \
  -d '{ "project_id": "proj_a1b2c3d4" }'
```

Opens (or focuses, if already open) that project in the app. Returns
`"status": "opening"` or `"already_open"`. Opening is **asynchronous** - poll
`GET /<project_id>/<page>` until it stops returning `project_not_open`. An
unknown id returns `404 project_not_found` with a hint to check `GET /projects`.

### `GET /projects/new`

```bash
curl http://127.0.0.1:8765/projects/new
```

Returns the field schema for `POST /projects/new` before you call it - the exact
list of valid `country` strings and `unit_system` options, plus
`currency_by_country` (what currency each country resolves to). Saves a caller
from guessing spellings and getting a `400` back.

### `POST /projects/new`

```bash
curl -X POST http://127.0.0.1:8765/projects/new \
  -d '{ "project_name": "Highway 5 Bridge", "country": "India", "unit_system": "metric" }'
```

Creates and opens a new project. Returns the generated `project_id` and the
chosen `currency`. Rules, mirroring the New Project dialog:

- `project_name` (required), `country` (required, must exactly match a name
  from the app's country list - a `400` on a bad value includes the full valid
  list), `unit_system` (optional, `"metric"` default or `"imperial"`).
- **Currency cannot be supplied - it is derived from the country** (e.g.
  India → INR), exactly like the dialog's auto-filled, disabled currency box.
  Sending a `currency` key is a `400`.
- Country, currency, and unit system are **permanent after creation** (they're
  the locked fields you see in `general_info`).

For both `open` and `new`, the project's API token is **not** returned - a
human reads it from **File → API Access** and hands it to whatever tool needs
data access. That's deliberate: it keeps a human in the loop between "any local
process can open a window" and "something can read/write project data."

---

## Getting the URL and token

With a project open in the GUI: **File → API Access**. The dialog shows:

- The full URL, e.g. `http://127.0.0.1:8765/proj_a1b2c3d4/bridge_data`
- The project's bearer token, with three controls:
  - **Regenerate Token** - issues a new token, invalidating the old one immediately
  - **Revoke Token** - clears the token entirely; every request against this
    project returns `401` until a new one is generated. Use this if you want to
    shut off API access for a project without disabling the API globally or
    closing the project.
  - **Generate Token** - shown in place of the above once a token has been
    revoked; creates a fresh token and restores access

The token is generated the moment the project opens and discarded when it closes -
requests against a closed/never-opened project always fail, regardless of token.
It's also held only in memory, never written to disk, so it resets on every app
restart.

---

## Authentication

Every request - `GET` and `POST` - must include the token as a header:

```
X-API-Token: <token>
```

Missing or incorrect token → `401 Unauthorized`, with a `documentation_url`
pointing at `/help`. This exists because a port on `127.0.0.1` is reachable by
anything else running on the machine, including JavaScript in other browser tabs
- not just tools you intentionally run. See the
[in-app dialog](#getting-the-url-and-token) for the current token; treat it like a
password for that project.

---

## Endpoints

Base URL: `http://127.0.0.1:<port>` - port defaults to `8765`; if it's busy
(e.g. a second app instance) the server automatically takes the next free port.
The port is never user-configurable - read the actual one from **File → API
Access** or the Settings page. Routes are generic -
`GET`/`POST /<project_id>/<page>` work for any page name in `available_pages`
(see [Self-documenting 404s](#self-documenting-404s)). The examples below use
`bridge_data`, the one page registered today.

### `GET /<project_id>/bridge_data`

Returns the current Bridge Data chunk **and** its field schema in one call - a
caller (an LLM/agent in particular) never needs a second lookup to know how to
build a valid `POST` body.

```bash
curl http://127.0.0.1:8765/proj_a1b2c3d4/bridge_data \
  -H "X-API-Token: <token>"
```

```json
{
  "project_id": "proj_a1b2c3d4",
  "chunk": "bridge_data",
  "data": {
    "bridge_name": "River Crossing",
    "user_agency": "State PWD",
    "project_country": "India",
    "location": "NH-48, km 212 over Narmada river",
    "bridge_type": "Girder",
    "span": 120.0,
    "carriageway_width": 10.5,
    "num_lanes": 4,
    "vehicle_path_direction": "Two Way",
    "footpath": "Footpath at both sides",
    "design_life": 100,
    "analysis_period": 100,
    "year_of_construction": 2026,
    "duration_construction_months": 18.0,
    "working_days_per_month": 22,
    "days_per_month": 30
  },
  "fields": [
    { "type": "section", "title": "Bridge Identification" },
    {
      "type": "field",
      "key": "bridge_name",
      "label": "Name of the Bridge",
      "description": "",
      "field_type": "text",
      "unit": null,
      "required": false,
      "default": null,
      "locked": false
    },
    {
      "type": "field",
      "key": "bridge_type",
      "label": "Type of Bridge",
      "description": "[Structural classification of the bridge (e.g. Girder, Arch, Cable-stayed).]",
      "field_type": "combo",
      "unit": null,
      "required": false,
      "default": null,
      "locked": false,
      "options": ["Girder", "Arch", "Cable-Stayed", "Suspension", "Truss", "Box Girder", "Slab", "Other"]
    },
    {
      "type": "field",
      "key": "span",
      "label": "Span",
      "description": "[Total span length of the bridge between supports.]",
      "field_type": "float",
      "unit": "(m)",
      "required": false,
      "default": 0.0,
      "locked": false,
      "min": 0.0,
      "max": 99999.0,
      "decimals": 2
    }
  ]
}
```

`fields` mirrors `BRIDGE_FIELDS` in `bridge_data/main.py`, in display order:

| Entry key | Meaning |
|---|---|
| `type` | `"section"` (visual header, no data) or `"field"` |
| `key` | The dict key to use in the `POST` body (fields only) |
| `label` / `description` | Human-readable title and help text |
| `field_type` | `"text"`, `"int"`, `"float"`, or `"combo"` |
| `options` | `combo` only - the exact list of valid strings |
| `min` / `max` / `decimals` | `int`/`float` only - valid range (and decimal places for `float`) |
| `unit` | Suffix shown in the GUI, e.g. `"(m)"`, or `null` |
| `required` | Whether the GUI enforces non-empty/non-zero before validation passes |
| `default` | Initial value if never set |
| `locked` | If `true`, this field is fixed - `POST` keeps its current value and reports it back via `warning` (see [Locked fields](#locked-fields)) |

### `POST /<project_id>/bridge_data`

Updates the Bridge Data chunk. Only the keys you send are changed - any field you
omit keeps its current value (see [Update semantics](#update-semantics--merge)). If
the Bridge Data page is currently visible/loaded in the GUI, the widgets update
live on screen; the value that ends up on screen and in storage is echoed back in
the response (numbers/combo values get coerced by the widgets).

```bash
# Change just one field - everything else is left untouched
curl -X POST http://127.0.0.1:8765/proj_a1b2c3d4/bridge_data \
  -H "X-API-Token: <token>" \
  -H "Content-Type: application/json" \
  -d '{ "location": "Jabalpur" }'
```

```json
{
  "project_id": "proj_a1b2c3d4",
  "chunk": "bridge_data",
  "data": { "...": "the full chunk after merging - unchanged fields plus your update" },
  "validation": {
    "errors": [],
    "warnings": []
  }
}
```

`validation` is `null` if the Bridge Data page has never been opened in this GUI
session yet (nothing to validate against) - the data is still saved and will
validate normally once the page is opened.

If the body includes a [locked field](#locked-fields) with a value that differs
from its current one, the response also includes `locked_fields_skipped` and a
`warning` - the rest of the update still goes through:

```json
{
  "project_id": "proj_a1b2c3d4",
  "chunk": "bridge_data",
  "data": { "...": "everything else you sent was applied; project_country was not" },
  "validation": { "errors": [], "warnings": [] },
  "locked_fields_skipped": ["project_country"],
  "warning": "These fields are locked and cannot be changed via the API - their current value was kept: project_country"
}
```

If the body contains a value that doesn't match the field's schema at all - an
option not in a combo's list, a non-numeric value for an `int`/`float` field, a
number outside its `min`/`max`, or a key that isn't a real field - the **whole
request is rejected** with `400` and nothing is changed:

```bash
curl -X POST http://127.0.0.1:8765/proj_a1b2c3d4/bridge_data \
  -H "X-API-Token: <token>" -H "Content-Type: application/json" \
  -d '{ "vehicle_path_direction": "Three-way" }'
```
```json
{
  "error": "invalid_field_values",
  "details": [
    "'vehicle_path_direction': 'Three-way' is not a valid option - must be one of ['One Way', 'Two Way']"
  ]
}
```

---

## Bridge Data fields

The authoritative field list is always the `fields` array returned by `GET` (it's
generated straight from `BRIDGE_FIELDS` in
[`bridge_data/main.py`](../components/bridge_data/main.py), so it can't drift out
of sync). Quick reference:

| Key | Type | Notes |
|---|---|---|
| `bridge_name` | string | |
| `user_agency` | string | Owner / responsible agency |
| `project_country` | string | **Locked.** Set once at project creation; any value sent for this key is ignored |
| `location` | string | Alignment, crossed feature, landmarks |
| `bridge_type` | string (combo) | `Girder`, `Arch`, `Cable-Stayed`, `Suspension`, `Truss`, `Box Girder`, `Slab`, `Other` |
| `span` | float (m) | |
| `carriageway_width` | float (m) | |
| `num_lanes` | int | |
| `vehicle_path_direction` | string (combo) | `One Way` or `Two Way` |
| `footpath` | string (combo) | `No footpath`, `Footpath at one side`, or `Footpath at both sides` |
| `design_life` | int (years) | Required |
| `analysis_period` | int (years) | Required |
| `year_of_construction` | int | Required |
| `duration_construction_months` | float (months) | Required |
| `working_days_per_month` | int | |
| `days_per_month` | int | |

### Locked fields

A field marked `"locked": true` in the schema (currently just `project_country`)
is fixed for the life of the project - the same fields that are disabled/greyed
out in the GUI. `POST` always keeps the current value for any locked key
regardless of what you send for it - it is never a `400` error, since sending
back a locked field's own current value is a normal side effect of "read the
record, change one thing, send the whole thing back." If your request would
actually have *changed* a locked field's value, the response still succeeds
(`200`) but includes `locked_fields_skipped` and a `warning` so you know that
one part of the request didn't take effect - see the example in
[POST](#post-project_idbridge_data) above.

---

## Errors

| Status | Body | Meaning |
|---|---|---|
| `401` | `{"error": "unauthorized", "documentation_url": "..."}` | Missing/incorrect `X-API-Token` |
| `404` | `{"error": "project_not_open", "usage": "...", "available_pages": [...], "documentation_url": "..."}` | `project_id` doesn't match any currently open project window |
| `404` | `{"error": "not_found", "usage": "...", "available_pages": [...], "documentation_url": "..."}` | The URL didn't match any known route at all (wrong path, typo'd page name, etc.) |
| `400` | `{"error": "invalid_json_body", "documentation_url": "..."}` | `POST` body wasn't valid JSON |
| `400` | `{"error": "invalid_field_values", "details": [...], "documentation_url": "..."}` | One or more keys/values in the body don't match the field schema (bad combo option, non-numeric value, out-of-range number, unrecognized key) - nothing is changed |

Every error response, of every status, carries `documentation_url` (→ `/help`) -
see [Discovery](#discovery--start-here-with-zero-prior-context).

### Self-documenting 404s

Every `404` (whether the project isn't open, or the URL just doesn't match
anything) also includes `usage` - a one-line explanation of the URL pattern - and
`available_pages` - the live list of pages currently exposed through the API.
This is deliberate: a caller (especially an LLM/agent) that guesses a wrong URL or
hits a project before it's open gets enough information to self-correct without a
human needing to paste in docs.

`401` responses stay compact - just `error` + `documentation_url`, no
`available_pages`/`usage` blob - since an unauthenticated caller shouldn't get a
free map of what a project currently contains, but pointing them at the (also
unauthenticated) `/help` endpoint costs nothing and is standard practice.

```json
{
  "error": "not_found",
  "usage": "Local GUI API. URL pattern: http://127.0.0.1:<port>/<project_id>/<page>. See documentation_url for full docs (no auth required).",
  "available_pages": ["bridge_data", "demolition_data", "financial_data", "general_info", "maintenance_data"],
  "documentation_url": "http://127.0.0.1:8765/help"
}
```

Note: attempting to change a [locked field](#locked-fields) is *not* one of these
errors - that request still succeeds (`200`), see `locked_fields_skipped` above.

---

## Update semantics - merge

`POST` merges: only the keys present in the body are changed; anything you omit
keeps its current value untouched. To change one field, send just that one field:

```json
{ "location": "Jabalpur" }
```

Locked fields (see [Locked fields](#locked-fields)) are pinned to their current
value even if you do include them in the body.

---

## Construction Works Data (table pages)

`str_foundation`, `str_sub_structure`, `str_super_structure`, `str_misc` hold
component groups of material/work-item rows, not flat fields:
`{component_name: [entry, ...]}`, where each entry is
`{id, values, meta, state}`. `GET` returns this data plus a `"schema"` object
(instead of `"fields"`) describing the entry shape and update rules - read it
before posting, it's the authoritative reference.

`POST` is **entry-granular and single-entry - no bulk operations**: the body is
`{component_name: [entry_patch]}` with exactly **one** component key and exactly
**one** patch in its list. Sending more than one component, or more than one patch,
is rejected with `400` - make one API call per material change.

- A patch **with** an `"id"` updates that entry - `values`/`state` keys given are
  merged into it, same as the form pages.
- A patch **without** an `"id"` creates a new entry, either from the catalog or
  manually:

```json
{ "Girder": [ { "id": "1b2c...-uuid", "values": { "rate": 56000.0 } } ] }
```

```json
{ "Girder": [ { "values": { "material_name": "Structural Steel", "unit": "MT",
                             "quantity": 12.5, "rate": 55000.0 } } ] }
```

To add a catalog item with the same source lineage the GUI's material search
dialog would give it, send the catalog row under `"catalog_item"`:

```json
{ "Girder": [
    { "catalog_item": { "name": "Rebar Fe500", "unit": "MT", "rate": 62000.0,
                         "db_key": "INDIA/Bihar/RCD SOR 2025" },
      "values": { "quantity": 8.0 } }
] }
```

Components (the group names themselves) are managed in the app on **this**
endpoint - a component name that doesn't already exist is rejected, not silently
created (the `add_from_catalog` shortcut below is the one exception). Entries are
never hard-deleted through this API; set `"state": {"in_trash": true}` to trash one
(`false` restores it), mirroring the GUI's trash tab - see also the simpler
`POST .../trash` shortcut below. Validation mirrors the GUI's material dialog
exactly (name/unit/quantity required, rate ≥ 0, recovery % ≤ 100, etc.) and is
atomic - one bad entry in the body rejects the whole request with `400` and
per-entry details.

**`"meta"` (source lineage, `db_original` snapshot, timestamps) is entirely
server-owned**: it's rejected if a caller sends it, and it's stripped out of
every `GET`/`POST` response - entries you see only ever have `id`/`values`/`state`.
It still exists internally (persisted to disk) so the app's own lineage rules keep
working; entries created through this API are additionally tagged
`created_via: "api"` in that hidden block, for audit purposes only - not something
you can read back over HTTP.

### `POST /{project_id}/{chunk}/add_from_catalog`

A simpler shortcut for the common case above: instead of searching the catalog
yourself and pasting the full row as `catalog_item`, just give the exact name and
let the server look it up. Adds **exactly one** material - no list wrapper:

```bash
curl -X POST http://127.0.0.1:8765/proj_a1b2c3d4/str_super_structure/add_from_catalog \
  -H "X-API-Token: <token>" \
  -d '{ "component": "Girder", "db_key": "INDIA/Bihar/RCD SOR 2025",
        "material_name": "Structural Steel main Girder (Fe 410 B)", "quantity": 12.5 }'
```

Rules:

- `component`, `db_key`, `material_name`, `quantity` are required. `db_key` comes
  from `GET /catalog/databases` or a search result. `material_name` must **exactly**
  match one row's name in that `db_key` (case/whitespace-insensitive) - no match or
  more than one match (ambiguous, e.g. the same name in two categories) rejects
  with `400` and, for the ambiguous case, the candidates' `src_id`s so you can fall
  back to `catalog_item` with the specific row.
- Unlike the main endpoint, **`component` is auto-created if it doesn't already
  exist** - same defaults the GUI uses for a brand-new component typed into its
  Add Material dialog. A failed request (e.g. material not found) never creates
  the component.
- `rate`, `carbon_emission`, `conversion_factor`, `src_id`, etc. all come from the
  matched row - not overridable here. Need to override something? Use
  `catalog_item` on the main endpoint instead.
- `include_in_carbon_emission` (optional): defaults to whatever the matched row
  supports. Asking for `true` when the row has no carbon data does **not** reject
  the material - it's still added, with this forced to `false` and a `warning` in
  the response explaining why.
- `include_in_recyclability` (optional, default `false`): if `true`, `scrap_rate`
  and `post_demolition_recovery_percentage` are **required in the same request** -
  catalog rows never carry recycling data, so there's nothing to fall back to.
- Rejects if a non-trashed entry in `component` already has this exact name
  (same duplicate-name rule the GUI's Add Material dialog enforces).
- Not supported on `str_component_registry` (or any non-`str_*` chunk) - `404
  not_supported`.

### `POST /{project_id}/{chunk}/add_manual`

Another shortcut, for when you want to supply the values yourself instead of
looking one up in the catalog. Flat `{component, values}` body - simpler than
the main endpoint's `{component: [entry_patch]}` list-wrapped form, and instead
of writing the full carbon unit string by hand (`"kgCO₂e/kg"` - that's a
subscript ₂, easy to get wrong), you give just the denominator:

```bash
curl -X POST http://127.0.0.1:8765/proj_a1b2c3d4/str_super_structure/add_manual \
  -H "X-API-Token: <token>" \
  -d '{ "component": "Girder",
        "values": { "material_name": "Cement", "unit": "kg", "quantity": 40, "rate": 350,
                     "carbon_emission": 0.9, "carbon_unit_den": "kg", "conversion_factor": 1.0 },
        "state": { "included_in_carbon_emission": true } }'
```

Rules:

- `component` and `values` are required at the top level; within `values`:
  `material_name`, `unit`, `quantity` (`> 0`), `rate` (`>= 0`) are required, everything
  else optional.
- **`carbon_unit_den` replaces `carbon_unit`** - give just the denominator (e.g.
  `"kg"`), the server builds `"kgCO₂e/<carbon_unit_den>"` itself. Sending
  `carbon_unit` directly is rejected with a message pointing you at
  `carbon_unit_den` instead. Required if `state.included_in_carbon_emission` is
  `true`.
- `state` is optional, only two keys accepted: `included_in_carbon_emission` and
  `included_in_recyclability` (both default `false`).
- `unit` must be a known code (see the chunk's `schema.units`) or paired with
  `custom_unit` (same shape as everywhere else in this API) to define a new one.
- Same as `add_from_catalog`: **`component` is auto-created if it doesn't already
  exist**, and duplicate active names in that component are rejected.
- Not supported on `str_component_registry` (or any non-`str_*` chunk) - `404
  not_supported`.

### `POST /{project_id}/{chunk}/trash`

Trash one entry by **id alone** - you don't need to know or send its component;
the server searches every component in the chunk for a matching id.

```bash
curl -X POST http://127.0.0.1:8765/proj_a1b2c3d4/str_super_structure/trash \
  -H "X-API-Token: <token>" \
  -d '{ "id": "1409a6f7-2f59-43c2-99c4-d40bf14f2536" }'
```

`"id"` is required and is the only key accepted. Idempotent - trashing an
already-trashed entry succeeds with no change. Unknown id → `400`. This is a
one-way shortcut; to **restore** an entry, use the main endpoint:
`POST /{project_id}/{chunk}` with
`{component: [{"id": ..., "state": {"in_trash": false}}]}`.

`str_component_registry` is bookkeeping (which components exist per chunk) - `GET`
only, `POST` returns `405 read_only_chunk`.

---

## Material catalog search

Before inventing a rate or emission factor for a new material, search the same
built-in SOR databases the GUI's material picker uses:

```bash
curl 'http://127.0.0.1:8765/catalog/search?q=steel+rebar&limit=5' \
  -H 'X-API-Token: <token>'
```

```json
{
  "query": "steel rebar",
  "items": [
    { "db_key": "INDIA/Bihar/RCD SOR 2025", "region": "Bihar", "category": "Foundation",
      "component": "Pile", "name": "Stainless Steel Rebars G410-L - Dia 6mm to 10mm",
      "unit": "MT", "rate": 158847, "src_id": "...", "carbon_emission": 2.5, ... }
  ],
  "total": 3, "limit": 5, "offset": 0,
  "note": "Each row can be sent directly as \"catalog_item\" in a POST to /{project_id}/str_* ..."
}
```

Not project-scoped - the catalog is the same for every project - but still
requires a token: **any currently-valid project token works**, not just the one
for a specific project. This keeps the catalog unreachable when no project is
open at all, matching the rest of the API.

| Endpoint | Purpose |
|---|---|
| `GET /catalog/databases` | List available SOR databases (`?country=`, `?region=`) |
| `GET /catalog/components` | Flat component list across all material types |
| `GET /catalog/items?db_key=&region=` | All rows across every material type, optionally filtered |
| `GET /catalog/tokens?db_key=&region=` | Vocabulary of real searchable words - check before guessing a search query |
| `GET /catalog/search?q=&db_key=&region=` | Full-text search across every material type - matches src_id, name, and description |

`items` and `search` are paginated: `limit` (default 50, max 200) and `offset`,
with `total` in the response so you know whether to page further.

A search result plugs straight into the Construction Works write path - send it
as `catalog_item` in a `str_*` POST (see
[Construction Works Data](#construction-works-data-table-pages) above) and the
server builds the full entry with correct source lineage, exactly like picking it
in the GUI's search dialog. Custom (user-defined) material databases aren't
searchable here yet - only the built-in SOR databases.

---

## Image upload fields

A field with `"field_type": "upload_img"` (e.g. `general_info`'s `agency_logo`)
normally stores a base64-encoded, compressed image - the same thing the GUI's own
Browse button produces. The API accepts either:

- a raw base64 string (as already stored), or
- a plain `http://`/`https://` image URL - the server downloads it, runs it
  through the exact same compression pipeline the GUI uses (same preset, same
  output format), and stores the result. Nothing is sent back over the wire
  except the final base64 in the response `data`.

```bash
curl -X POST http://127.0.0.1:8765/proj_a1b2c3d4/general_info \
  -H "X-API-Token: <token>" -H "Content-Type: application/json" \
  -d '{ "agency_logo": "https://example.com/logo.png" }'
```

If the URL can't be fetched or decoded as an image, the request is rejected with
`400 invalid_field_values` (same shape as a schema validation error) and nothing
is changed - the download/convert step runs before anything is written. There's a
15 MB download ceiling and a 15s fetch timeout.

A schema field with `"format": "base64_or_url"` in its `GET` response is an
`upload_img` field, so a caller can tell without guessing.

---

## Disabling the API

**Settings → Local API → Enable local API server** (unchecked = server never
starts). Takes effect after restarting the app.

---

## Extending to more pages

The API is split into a generic engine and per-page registrations, so adding a
page never touches the engine:

- **`registry.py`** - chunk-agnostic: `CHUNK_PAGE_MAP`, `register_chunk()`,
  `describe_chunk_fields()`, `validate_payload_keys()`. Knows nothing about
  Bridge Data or any specific page.
- **`bridge.py`** - `ApiBridge`, the Qt-main-thread marshaling engine. Also
  chunk-agnostic; dispatches purely off whatever's in `CHUNK_PAGE_MAP`.
- **`server.py`** - Flask routes. Generic (`/<project_id>/<chunk>`); looks
  `chunk` up in `CHUNK_PAGE_MAP` at request time. Never needs editing to add a
  page.
- **`pages/`** - one module per page, each calling `register_chunk()` as an
  import-time side effect. `pages/__init__.py` imports all of them, so the
  whole API surface is wired up by one `import gui.api.pages`.

Real examples to copy from, each showing a different variant:

- `pages/bridge_data.py` - `warn_rules` as a module-level dict
- `pages/general_info.py` - no warn rules at all; also shows that the chunk name
  the API uses doesn't have to match the component's folder name - `general_info`
  lives under `gui/components/global_info/`, because that's the chunk name the
  engine actually stores it under
- `pages/maintenance.py` - warn ranges declared inline per-field
  (`FieldDef(..., warn=(...))`) instead of a module-level dict; `register_chunk()`
  picks either style up automatically
- `pages/financial_data.py`, `pages/demolition.py` - two more `warn_rules`-dict
  examples

To add a new page, the shape is always:

```python
from three_ps_lcca_gui.gui.components.<folder>.main import (
    <FIELDS_LIST>, <WidgetClass>,
)
from ..registry import register_chunk

register_chunk(
    "<chunk_name>",             # whatever controller.get_chunk()/save_chunk_data() use
    page_name="<Page Name>",    # key in ProjectWindow.widget_map
    widget_cls=<WidgetClass>,   # for its `_LOCKED` set, if any
    field_defs=<FIELDS_LIST>,   # the page's FieldDef/Section list
    # warn_rules=...,           # optional, only if not using inline FieldDef(warn=...)
)
```

Then add `from . import <module>  # noqa: F401` to `pages/__init__.py`. That's it
- `server.py`, `bridge.py`, and `registry.py` need no changes. `GET`/`POST
/<project_id>/<chunk_name>` work immediately, with the same schema, merge
semantics, locked-field handling, and validation every other page gets, because
all of that logic already runs generically off `CHUNK_PAGE_MAP`. No changes are
needed in the page widget itself either - it only needs the `get_data_dict()` /
`load_data_dict()` / `validate()` interface every `BaseDataWidget` subclass
already has.
