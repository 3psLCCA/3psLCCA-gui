---
name: 3pslcca-local-api
description: Guide for reading, updating, and managing project data in the running 3psLCCA desktop application over the local HTTP API.
---

# 3psLCCA Local GUI API Guide

This skill documents how to interact with the local HTTP API exposed by the running **3psLCCA** desktop app.

> **Always check `GET /help` first.** This document is a static snapshot and the live app is the source of truth: endpoints, fields, enums, and validation rules can change between app versions. Before relying on any endpoint, field name, or option listed below, call `GET /help` (no token required) to pull the current, live JSON schema — and prefer what it says over this file if the two ever disagree.

> [!IMPORTANT]
> **Golden rule — applies everywhere in this skill, not just the workflows below where it's repeated:**
> * **Never assume any value on the user's behalf — always ask.** This covers material grade/type, quantity, rate, database/SOR choice, component name, project settings, or any other field that affects cost, carbon, or design — even when a "typical" or "common" value seems obvious. Don't silently pick a default; stop and ask a specific question, and help the user decide by explaining the options and what each implies, plus what you'd look up next once they choose.
> * **If a catalog search (or any lookup) turns up nothing usable** — zero results, or only weak/partial matches after trying reasonable alternate tokens — don't force a near-match into place and don't fail silently either. Tell the user plainly, using language like **"No results" / "Incomplete search"** (e.g. *"No results found in the [db name] database for [activity/material] — search was incomplete even after trying [tokens tried]."*), then suggest adding the item as a **manual entry** (`POST /{project_id}/{chunk}/add_manual`) and ask them for the values it needs (material name, unit, quantity, rate, and carbon figure if known). Offer to try a different SOR database too, but let the user choose — never assume manual entry or a different database is what they want.
> * **Always read a catalog item's full description before suggesting it** — don't match on name/tokens alone. A material name or search token can look right while the description reveals a different spec, size, unit basis, or scope than what's needed. Check the description field returned by `GET /catalog/search` / `GET /catalog/items` for every candidate row, and only present it to the user (in the results table) once you've confirmed the description actually fits the activity — if it doesn't, treat that row as a non-match rather than including it.

---

## 1. Setup & Discovery

* **Base URL**: `http://127.0.0.1:8765` (bound to localhost only; the port auto-increments if 8765 is busy and is not user-configurable).
* **Detailed Docs**: Call `GET /help` to retrieve the full, live API documentation and JSON schemas (`GET /` serves the same content as an HTML page for humans).
* **List All Projects**: `GET /projects` — no token needed. Returns `{"projects": [{project_id, display_name, created_at, last_modified, status, open}]}`. Use the `"open"` flag (not `"status"`) to know if a project is reachable by data endpoints — `"status": "locked"` can still apply to a project that's open in this same app instance.
* **Always Show Project Names, Not Just IDs**: Whenever `GET /projects` or `GET /projects/active` is called for discovery (e.g. before opening a project, before creating a new one, or when the user asks "what projects do I have"), always present the list to the user by `display_name` (with `open`/`status` noted), never bare `project_id`s. `project_id` is an internal handle for subsequent API calls — it should stay behind the scenes in your own tool calls, not be the thing the user reads. If the user refers to a project by name, resolve it against this list yourself rather than asking them for the id.
* **Active Projects**: `GET /projects/active` — no token needed. Same shape as above, filtered to currently-open projects, plus a `"count"`.
* **Opening a Project**: If a project is closed, call `POST /projects/open` with `{"project_id": "..."}`. Opening is asynchronous — poll any data endpoint (`GET /{project_id}/{page}`) until it stops returning `404 project_not_open`. Unknown ids return `404 project_not_found`.
* **Creating a Project**: `GET /projects/new` first to fetch the valid `country`/`unit_system` options and the country-to-currency map — don't guess these. Then `POST /projects/new` with `{"project_name": "...", "country": "...", "unit_system": "metric"|"imperial"}`. Currency is derived automatically from `country` and cannot be supplied — sending a `"currency"` key is a 400. Country, currency, and unit system are permanent after creation.

---

## 2. Authentication

* **Header**: `X-API-Token: <token>` (required for all data and catalog endpoints).
* **Not required for**: `GET /`, `GET /help`, `GET /projects`, `GET /projects/active`, `GET /projects/new`, `POST /projects/open`, `POST /projects/new`, `GET`/`POST /{project_id}/get_tokens`.
* **Obtaining a Token — try the automatic handshake first**: Call `GET /{project_id}/get_tokens`. This shows an Allow/Deny popup in the desktop app — a human has to click something, so expect the call to block for a while (it can take up to ~2 minutes; don't treat a slow response as a hang). Only fall back to asking the user to paste a token manually if this fails.

  | Result | Status | What it means |
  | :--- | :--- | :--- |
  | User clicked Allow | `200` | `{"ok": true, "token": "..."}` — use it directly. |
  | Project isn't open | `404` | `project_not_open` — open it first, then retry once. |
  | User clicked Deny / closed the popup | `403` | `denied` — that one request was refused; asking again will show the popup again (up to the cap below). |
  | Already handed out once this session | `403` | `token_already_delivered` — this project's token was already sent over HTTP once; it will not be sent again automatically. |
  | Asked (and denied) too many times this session | `429` | `too_many_requests` — the popup cap for this project was hit; no more automatic popups until the project is closed and reopened. |

  This is a **one-shot** handshake, not something to poll or retry in a loop — one attempt, then fall back.

  ```python
  import urllib.request, urllib.error, json

  def get_token(project_id: str, base_url="http://127.0.0.1:8765") -> str:
      try:
          with urllib.request.urlopen(f"{base_url}/{project_id}/get_tokens", timeout=120) as resp:
              return json.loads(resp.read())["token"]
      except urllib.error.HTTPError as e:
          body = json.loads(e.read())
          print(f"Automatic token request failed ({e.code}): {body.get('error')} - {body.get('message', '')}")
          # Fall back: ask the user directly - do not retry get_tokens in a loop.
          return input(f"Paste the API token for {project_id} (from File > API Access): ").strip()
  ```

  If the automatic call fails for any reason above, ask the user to retrieve it from the desktop app via **File > API Access** (with the project open) and paste it — the dialog there shows the token with Generate/Regenerate/Revoke controls, and is always available as a manual fallback regardless of what `/get_tokens` returned.
* **Reset Behavior**: Tokens live in memory only — they reset on every app restart and clear when the project window closes. A token that worked yesterday will 401 today if the app was restarted since.
* **On `401 Unauthorized`**: Don't just retry. First call `GET /projects/active`. If the project isn't listed, its window was closed and the old token is gone for good — reopen it via `POST /projects/open` and get a fresh token (try `/get_tokens` again, or ask the user). If it is listed, the token is simply stale or mistyped — ask the user to re-check it.

---

## 3. Core Constraints & Conventions

* **Schema Auto-Discovery**: Always call `GET /{project_id}/{page}` first. The response includes both the current `"data"` and a `"fields"` list defining types, units, validation ranges, option enums, defaults, and read-only/locked flags for that specific page — enough to build a valid POST body without a second lookup.
* **Merge Updates**: Updates merge (PATCH-like), never replace. POST only the fields you want to change; omitted fields keep their current value.
* **Atomic Validation**: Validation is strict and all-or-nothing — a bad enum option, wrong type, out-of-range number, or unrecognized key rejects the *entire* request with `400` and per-field details in `"details"`. Nothing is partially applied.
* **Locked Fields**: Fields with `"locked": true` in the schema (e.g., country, currency, unit system) can never be changed via the API. A POST silently keeps their current value and lists them in `"locked_fields_skipped"` rather than erroring.
* **Image Uploads**: Fields with `"field_type": "upload_img"` accept either raw base64 data or a plain http(s) image URL — URLs are downloaded and converted automatically.
* **Single-Entry Constraint (str_* chunks)**: For Construction Works chunks (`str_foundation`, `str_sub_structure`, `str_super_structure`, `str_misc`), each `POST` to `/{project_id}/{chunk}` can only create/update **exactly one entry, in exactly one component**. Batching multiple entries or components in one call is rejected.
* **Request Bodies**: Parsed as JSON regardless of the `Content-Type` header sent.
* **Catalog Scope**: `/catalog/*` endpoints are not project-scoped (the material database is shared across all projects) but still require a token — any currently-valid project token works. Always search the catalog before inventing rate or carbon values: `GET /catalog/search?q=...`, then send a result as `"catalog_item"` in a POST to a `str_*` chunk.
* **Locked Projects Reject All Writes**: A project locks itself the moment `GET /validate` (or a human) runs a calculation with zero errors — this protects the computed results from being silently invalidated. While locked, **every** write endpoint (`POST /{project_id}/{page}`, `add_from_catalog`, `add_manual`, `trash`, and `GET /validate` itself) returns `423 project_locked`; `GET` reads keep working. Call `POST /{project_id}/unlock` first — see Section 4.

---

## 4. Data & Catalog Endpoints Reference

### Token endpoint
* **`GET`/`POST /{project_id}/get_tokens`** *(no token required — this is how you get one)* — One-shot handshake that pops an Allow/Deny dialog in the desktop app; blocks until a human responds (up to ~2 minutes) or one of the terminal cases in Section 2 fires (`denied`, `token_already_delivered`, `too_many_requests`, `project_not_open`). Returns `{"ok": true, "token": "..."}` on success. See Section 2 for the full result table, retry rules (never poll/retry this in a loop — one attempt, then fall back to File > API Access), and a ready-to-use Python helper.

### Project pages
Valid `{page}` values: `bridge_data`, `demolition_data`, `financial_data`, `general_info`, `maintenance_data`, `str_component_registry`, `str_foundation`, `str_misc`, `str_sub_structure`, `str_super_structure`. (Confirm against `GET /help` — this list can change with app updates.)

* **`GET /{project_id}/{page}`** *(token required)* — Read a page's current data plus its full field schema in one call.
* **`POST /{project_id}/{page}`** *(token required)* — Update a page. Send a JSON object with any subset of fields; omitted fields are untouched. Response includes `"data"`, the GUI's own `"validation"` result, and `"locked_fields_skipped"`/`"warning"` if relevant.

### Construction Works (str_*) helper endpoints
* **`POST /{project_id}/{chunk}/add_from_catalog`** — Add exactly one catalog material by exact name: `{"component", "db_key", "material_name" (exact, case-insensitive), "quantity", ...optional flags}`. Note: If a material name exists under multiple catalog categories (e.g. `TMT Fe500 Reinforcement Steel Bars` in both Foundation and Sub Structure), `add_from_catalog` will return a `400 Bad Request`. In such cases, disambiguate by calling `POST /{project_id}/{chunk}` with the full `"catalog_item"` JSON object (which explicitly specifies `"category"` and `"component"`) along with `"values": {"quantity": <n>}`.
* **`POST /{project_id}/{chunk}/add_manual`** — Add exactly one material with your own values, no catalog lookup: `{"component", "values": {"material_name", "unit", "quantity", "rate" required, ...optional}, "state": {"included_in_carbon_emission"?, "included_in_recyclability"?}, "custom_unit"?}`. Note the flat `{component, values}` shape — different from the generic endpoint's list-wrapped form. `carbon_unit_den` only needs the denominator (e.g. `"kg"`); the server builds the full `"kgCO₂e/<unit>"` string.
* **`GET /{project_id}/{chunk}/trash`** — List only trashed entries (`state.in_trash=true`) across all components; components with none are omitted.
* **`POST /{project_id}/{chunk}/trash`** — Trash or restore one entry by id: `{"id": "<entry-uuid>", "untrash"?: bool}` (default `false`). Idempotent.

### Results & calculation (not chunk-scoped)
* **`GET /{project_id}/validate`** *(token required)* — Runs the same aggregate check the GUI's Calculate button runs: every page's own validation, keyed by page name (`{"errors": {...}, "warnings": {...}}` — errors block calculation, warnings are advisory only and never block anything). If there are **zero errors**, it also runs the real life-cycle-cost calculation synchronously (this call waits for it) and **locks the project**, exactly like a successful native Calculate click. On success, `"results"` (`{results, analysis_period, currency}`) holds the actual computed output — this is the *only* way to read a calculation result via the API, since it's never written to disk. `"page_chunks"` maps each page name in `errors`/`warnings` to the chunk id(s) to fix it. Returns `423 project_locked` instead of recalculating if the project is already locked.
* **`POST /{project_id}/unlock`** *(token required)* — The only way to clear a locked project. Clears the cached results and re-enables editing on every page; does not itself change any input data. Idempotent — unlocking an already-unlocked project returns `200` with `"status": "already_unlocked"`.

### Materials catalog
* **`GET /catalog/databases`** — List available Schedule of Rates (SOR) databases (optional filters: `country`, `region`).
* **`GET /catalog/components`** — Flat list of all component names across every material type.
* **`GET /catalog/items?db_key=&region=&limit=&offset=`** — All catalog rows, optionally filtered (default limit 50, max 200). Note: `component` filter parameter is removed.
* **`GET /catalog/tokens?db_key=&region=`** — Vocabulary of real searchable words extracted from all `name` and `description` fields in that specific SOR database file (with stop words, numbers, and single letters removed). Check this **before** guessing a search query to verify indexed vocabulary. Note: `component` filter parameter is removed.
* **`GET /catalog/search?q=<term>&db_key=&region=&limit=&offset=`** — Full-text search across material names and descriptions (the same matcher the GUI's material dialog uses). Each result row can be sent verbatim as `"catalog_item"` in a POST, or referenced via `add_from_catalog`.

---

## 5. Workflow: Creating a New Project

When the user asks to start/create a new project (e.g. "set up a new bridge project", "create a project for Highway 5"):

### Step 1: Check for an Existing Project First
1. Call `GET /projects` and present the existing projects **by name** (`display_name`), each with its `open`/`status` state, in case the user actually meant to reuse or reopen one instead of creating a duplicate.
2. If none look like a match, or the user confirms they want a new one, proceed.

### Step 2: Fetch Valid Options Before Asking
1. Call `GET /projects/new` to retrieve the valid `country` list, the `unit_system` options, and the country→currency map. Never guess a country string — an invalid one is rejected with a 400 listing all valid values, so it's cheaper to fetch them up front.
2. Ask the user for: **project name**, **country** (from the fetched list), and **unit system** (metric/imperial, default metric if unspecified). Show the currency that will be derived from their chosen country so there are no surprises later — it can't be changed afterward.

### Step 3: Create and Confirm
1. `POST /projects/new` with `{"project_name", "country", "unit_system"?}`. Do **not** include a `"currency"` key — it's derived automatically and sending one is rejected with a 400.
2. The response returns the new `project_id`, derived `currency`, and `status: "created"`. The project is also opened automatically as part of creation.
3. Report back to the user by the **project name** they chose, not the raw id: e.g. "Created and opened **Highway 5 Bridge** (India, metric, ₹ INR)."

### Step 4: Ask for the API Token Before Any Data Call
1. Any subsequent read/write against this project (`GET`/`POST /{project_id}/{page}`, catalog adds, etc.) needs `X-API-Token`, and the API never returns one itself — this is deliberate, to keep a human in the loop.
2. Ask the user to open **File > API Access** in the desktop app (the new project should already be the active window) and share the token shown there.
3. Do not proceed with any data endpoint call until the token is provided. If the user later reports a 401, follow the standard troubleshooting flow in Section 8 rather than assuming the token they gave was wrong — the project window may have been closed/reopened in the meantime, which issues a new token.

---

## 6. Workflow: Adding Material in Construction Work Data (str work data)

When instructed to add construction materials (e.g., "add materials related for construction of super structure"), the AI agent **MUST** follow this interactive step-by-step workflow:

### Step 1: List and Identify Available Databases
Check the active Schedule of Rates (SOR) database set in the project:
1. Retrieve the current settings from the `general_info` chunk under the `sor_database` field. Note: For freshly created projects, `sor_database` field options in `general_info` may be empty `[]`. Attempting to POST `sor_database` via API will return a 400 validation error; simply pass the desired `db_key` directly in all `/catalog/*` API endpoints.
2. Query `GET /catalog/databases` to list all available material suggestions databases on the machine.

### Step 2: Confirm Database Usage
**Do not proceed without user confirmation.** Present the active database to the user and explicitly ask/confirm:
* *"Would you like to use the active database [<db_name>] for suggesting materials, or switch to a different available database?"*

> [!IMPORTANT]
> **Never assume a value on the user's behalf — always ask.** This applies to every material grade, type, quantity, database choice, component name, and any other field that affects cost, carbon, or design — even when a "typical" or "common" value seems obvious. Guessing a plausible-looking grade (e.g. defaulting to M35 because it's common) can silently misprice or misdesign the structure, and the user has no way to catch it later since it looks like a deliberate choice. When something is ambiguous or unspecified, stop and ask a specific question (using the question bank above as a model) rather than proceeding with an assumption — and help the user answer it: explain the options, what each implies, and what you'd need to look up next once they choose.
>
> **If the SOR catalog has no matching items or works for what's needed** (`GET /catalog/search`/`GET /catalog/tokens` return nothing usable, even after trying reasonable alternate tokens), don't force a near-match catalog item into place and don't give up silently either. Tell the user plainly that the active database has no matching entry, and suggest adding it as a **manual entry** instead (`POST /{project_id}/{chunk}/add_manual`) — then ask them for the values a manual entry needs: material name, unit, quantity, rate, and (if relevant) carbon emission figure. Offer to try a different SOR database first if one might have the item, but let the user decide rather than assuming manual entry — or a different database — is what they want.

### Step 3: List Construction Activities (Tasks) and Ask Design Questions
Once the database is confirmed, outline the construction tasks matching the user's high-level work request (using the **Bridge Construction Stages & Chunk Mapping Reference** in Section 7 as a guide):
1. List all structural activities/stages involved (e.g. for "super structure", list Girder Reinforcement, Prestressing Works, Girder Concreting, Deck Slab, Railings, etc.).
2. **Ask targeted, material-specific design questions before searching the catalog** — never assume a default grade, type, or method. The right grade/type is what actually determines which catalog tokens will return useful results, so this step isn't optional politeness, it's a prerequisite for Step 4. Use the bank below as a starting point, and **develop additional questions the same way** for any material category not listed: name the category, ask for its grade/type/spec, and note why it matters for the search.

**Example clarifying-question bank (by material category):**

| Material Category | Example Question to Ask the User | Why It Matters |
| :--- | :--- | :--- |
| **Concrete** | "What concrete grade should be used for the [pile cap / pier / girder / deck slab]? (e.g. M25, M30, M35, M40, M45, M50)" | Grade is a direct search token (`m35`, `m40`, ...) and drives both rate and carbon-emission lookup — a wrong grade returns the wrong catalog row entirely. |
| **Reinforcement Steel (Rebar)** | "What grade of reinforcement/HYSD steel should I use — Fe500, Fe500D, Fe550, or Fe550D?" | Different grades are separate catalog line items with different rates; also affects design capacity, so this shouldn't be assumed. |
| **Structural Steel** | "For the [steel girder / cross bracing / fabrication work], what structural steel grade applies — Fe410, Fe440, or another IS grade?" | Structural vs reinforcement steel are different components entirely; grade narrows the catalog search and avoids picking rebar by mistake. |
| **Prestressing Steel** | "For prestressing, are you using strands or high-tensile wires, and what tensile grade?" | "Strands" and "wires" are distinct searchable tokens with different unit rates; picking the wrong one misprices the whole girder line. |
| **Bearings** | "What type of bearing is specified — POT, PTFE, or elastomeric?" | Each bearing type is a separate catalog entry with a very different rate; there's no sensible default to assume. |
| **Waterproofing** | "What waterproofing membrane grade should be used — VG30 or VG40 bitumen, or a different spec?" | Grade affects both the token used in search and the correct unit rate. |
| **Expansion Joints** | "What type of expansion joint is required — strip seal, modular, or another type?" | Joint type materially changes both cost and the catalog component it belongs to. |
| **Railings / Crash Barriers** | "Should the railing/crash barrier be precast RCC, cast-in-situ, or steel? What concrete/steel grade if RCC?" | Determines both the search tokens and whether it's a concrete or steel-dominant line item. |
| **Wearing Course / Road Marking** | "What wearing course material is specified — mastic asphalt, or a different mix? Any road marking paint type (thermoplastic, etc.)?" | These are often mistaken for one another in the catalog if the material type isn't pinned down first. |

If the user's initial request already states a grade/type ("M40 girder concrete", "Fe500D rebar"), don't re-ask that one — only ask about the categories still left ambiguous. If a new/custom activity is involved that isn't in this bank, follow the same pattern: identify the material category, ask what grade/type/spec applies, and state briefly why it affects the search (usually: it's a distinct catalog token, or it changes the rate/component).

### Step 4: Find Search Keywords via Catalog Tokens
To prevent guessing search queries that return zero results:
1. Call `GET /catalog/tokens?db_key=<db_key>&region=<region>` to fetch the complete set of unique words extracted from all `name` and `description` fields in that specific SOR database file (built via `devtools/tokenized.py`). Note: The `component` parameter is no longer used.
2. Check whether your target search terms exist in the token vocabulary. If a base word is missing, search for alternative tokens or root forms (e.g., `cofferdams` vs `cofferdam`, `levelling` vs `leveling`).
3. Note regional/SOR naming conventions: For example, in Maharashtra PWD SSR, pile cap items may be listed under `well cap` or `caps`, and `levelling` uses British double-l spelling.

### Step 5: Search, Discuss, and Add (NO ASSUMPTIONS)
Once suitable search keywords are identified:
1. Perform full-text search query using `GET /catalog/search?q=<token>&db_key=<db_key>`. If it returns no results, try a couple of alternate tokens from `GET /catalog/tokens` before concluding there's genuinely no match — don't stop after a single query.
2. If `add_from_catalog` fails with 400 because a material name exists in multiple categories (e.g. `TMT Fe500 Reinforcement Steel Bars`), send the full `catalog_item` object with `category` and `component` specified via `POST /{project_id}/{chunk}`.
2. **If no matching item/work exists in the active SOR database after reasonable retries**: say so directly to the user (e.g. "The [db name] database has no entry for [activity/material] — I couldn't find a match even after trying [tokens tried]."). Then suggest one of: (a) trying a different available SOR database (list the alternatives from `GET /catalog/databases`), or (b) adding it as a **manual entry** via `POST /{project_id}/{chunk}/add_manual`. If they choose manual entry, ask for the required values one at a time if needed: material name, unit, quantity, rate, and carbon emission figure if known — never fill these in yourself.
3. **Before presenting any candidate, read its full `description` field** (from `GET /catalog/search` / `GET /catalog/items`) — don't rely on the name or matched token alone. Drop any row whose description doesn't actually fit the activity/spec discussed with the user, even if the name looked promising.
4. **Always present the matched catalog items as a table** with the columns:
   `Sr no. | Stage / Activity | Database Item Name / Manual Option | Rate / Unit | Target Chunk & Component`
3. **Ask the user to enter the Sr no. and Qty** of the item they want to add.
4. **CRITICAL**: **DO NOT ASSUME ANYTHING**. Only add the selected items to the corresponding chunk (e.g., `POST /{project_id}/{chunk}/add_from_catalog` or `/add_manual`) after the user explicitly selects/confirms the item by Sr no. and specifies its quantity.
5. **VERIFICATION**: **After adding any material, always query `GET /{project_id}/{chunk}` to verify the item exists** in the chunk's data registry under the correct component, and display this confirmation to the user.

---

## 7. Bridge Construction Stages & Chunk Mapping Reference

To ensure materials are added to the correct tabs and components, reference this standard bridge construction mapping list.

> [!NOTE]
> **Custom & Dynamic Activities**: If the user requests a construction activity not listed below (or wants to add a new custom activity), search the catalog vocabulary using `/catalog/tokens` first. Note that **as per the database being used, the keywords may change. Always respect the tokens returned by the `/catalog/tokens` endpoint.** If matching items are found, add them. If not found, add the activity as a **manual entry** (`POST /{project_id}/{chunk}/add_manual`) using the component name and values (unit, rate, quantity) specified by the user.

### Stage-to-Chunk Mapping Table (with Sample Search Tokens)

| Stage | Construction Activity | Target Chunk | Target Component Name | Sample Key Search Tokens (Database Words) |
| :--- | :--- | :--- | :--- | :--- |
| **1** | Site Preparation – Excavation | `str_foundation` | `Excavation` | `excavation`, `foundation`, `dry`, `wet`, `soil`, `rock` |
| **2** | Pile Foundation Construction | `str_foundation` | `Pile` | `pile`, `piles`, `boring`, `concreting`, `bored`, `m35`, `m25` |
| **3** | Pile Reinforcement | `str_foundation` | `Pile` | `reinforcement`, `bar`, `bars`, `hysd`, `steel`, `pile` |
| **4** | Levelling Course | `str_foundation` | `Pile Cap` | `plain`, `cement`, `concrete`, `pcc`, `m15`, `m10`, `leveling` |
| **5** | Pile Cap Reinforcement | `str_foundation` | `Pile Cap` | `reinforcement`, `bar`, `bars`, `hysd`, `steel`, `cap` |
| **6** | Pile Cap Concreting | `str_foundation` | `Pile Cap` | `rcc`, `concrete`, `m35`, `cap`, `batching`, `pump` |
| **7** | Pile Cap Waterproofing | `str_misc` | `Waterproofing` | `waterproofing`, `water`, `proofing`, `bitumen`, `vg30`, `vg40` |
| **8** | Pier Reinforcement | `str_sub_structure` | `Pier` | `reinforcement`, `bar`, `bars`, `hysd`, `steel`, `pier` |
| **9** | Pier Concreting | `str_sub_structure` | `Pier` | `rcc`, `concrete`, `m35`, `pier`, `batching`, `pump` |
| **10** | Pier Cap Reinforcement | `str_sub_structure` | `Pier Cap` | `reinforcement`, `bar`, `bars`, `hysd`, `steel`, `cap` |
| **11** | Pier Cap Concreting | `str_sub_structure` | `Pier Cap` | `rcc`, `concrete`, `m35`, `cap`, `batching`, `pump` |
| **12** | Bearing Pedestal Reinforcement | `str_sub_structure` | `Pedestal` | `reinforcement`, `bar`, `bars`, `hysd`, `steel`, `pedestal` |
| **13** | Bearing Pedestal Concreting | `str_sub_structure` | `Pedestal` | `rcc`, `concrete`, `m35`, `pedestal`, `batching` |
| **14** | Bearing Installation | `str_sub_structure` | `Bearings` | `bearing`, `bearings`, `pot`, `ptfe`, `elastomeric` |
| **15** | Girder Reinforcement | `str_super_structure` | `Girder` | `reinforcement`, `bar`, `bars`, `hysd`, `steel`, `girder` |
| **16** | Prestressing Works | `str_super_structure` | `Girder` | `high`, `tensile`, `steel`, `wires`, `strands`, `prestressing` |
| **17** | Girder Concreting | `str_super_structure` | `Girder` | `psc`, `rcc`, `m40`, `m45`, `m50`, `superstructure`, `girder` |
| **18** | Girder Transportation & Erection | `str_super_structure` | `Girder` | `transport`, `placement`, `precast`, `erection` *(Manual)* |
| **19** | Steel Girder Fabrication & Erection | `str_super_structure` | `Girder` | `structural`, `steel`, `fabrication`, `erection`, `fe410` |
| **20** | Steel Cross Bracing Installation | `str_super_structure` | `Cross Bracings` | `bracing`, `cross`, `steel`, `angle`, `sections` |
| **21** | Protective Steel Coating | `str_misc` | `Asphalt, Utilities and Other Materials` | `metalizing`, `primer`, `aluminium`, `paint`, `coating` |
| **22** | Diaphragm Reinforcement | `str_super_structure` | `Diaphragm` | `reinforcement`, `bar`, `bars`, `hysd`, `steel`, `diaphragm` |
| **23** | Diaphragm Concreting | `str_super_structure` | `Diaphragm` | `rcc`, `concrete`, `m35`, `diaphragm`, `batching`, `pump` |
| **24** | Deck Slab Reinforcement | `str_super_structure` | `Deck Slab` | `reinforcement`, `bar`, `bars`, `hysd`, `steel`, `deck`, `slab` |
| **25** | Deck Slab Concreting | `str_super_structure` | `Deck Slab` | `rcc`, `concrete`, `m35`, `deck`, `slab`, `batching`, `pump` |
| **26** | Deck Waterproofing | `str_misc` | `Waterproofing` | `waterproofing`, `water`, `proofing`, `bitumen`, `vg30`, `vg40` |
| **27** | Wearing Course | `str_misc` | `Asphalt, Utilities and Other Materials` | `wearing`, `course`, `mastic`, `asphalt`, `12mm` |
| **28** | Expansion Joint Installation | `str_misc` | `Asphalt, Utilities and Other Materials` | `expansion`, `joint`, `joints`, `strip`, `seal` |
| **29** | Crash Barrier Construction | `str_misc` | `Railing  & Crash Barrier & Median` | `crash`, `barrier`, `m30`, `concrete`, `hysd`, `reinforcement` |
| **30** | Median / Divider Construction | `str_misc` | `Railing  & Crash Barrier & Median` | `median`, `divider`, `m30`, `concrete`, `hysd`, `reinforcement` |
| **31** | Bridge Railing Installation | `str_misc` | `Railing  & Crash Barrier & Median` | `railing`, `railings`, `precast`, `rcc`, `m30`, `mild`, `steel` |
| **32** | Road Marking | `str_misc` | `Asphalt, Utilities and Other Materials` | `road`, `marking`, `paint`, `thermoplastic`, `yellow`, `white` |
| **33** | Protective Rebar Treatment | `str_misc` | `Asphalt, Utilities and Other Materials` | `anti-corrosive`, `paint`, `treatment`, `epoxy`, `coated` |

### Additional Bridge Components (Mapped if applicable)

* **Abutment Walls & Abutment Caps**: Map to `str_sub_structure` chunk under component `Abutment` (or `Pier Cap` if generic). Tokens: `abutment`, `cap`, `concrete`, `reinforcement`.
* **Return Walls & Wing Walls**: Map to `str_sub_structure` chunk under component `Abutment` or `Pier`. Tokens: `wing`, `wall`, `walls`, `concrete`.
* **Approach Slabs**: Map to `str_misc` chunk under component `Asphalt, Utilities and Other Materials`. Tokens: `approach`, `slab`, `reinforcement`.
* **Drainage Spouts / Gutter Pipes**: Map to `str_misc` chunk under component `Drainage`. Tokens: `drainage`, `spouts`, `pipe`, `gutter`.
* **Weep Holes (with PVC pipes & filter media)**: Map to `str_sub_structure` (Abutment) or `str_misc` (Drainage). Tokens: `weep`, `holes`, `pvc`, `pipe`, `filter`.

---

### Category Token Search Helper (Merged All-Database Vocabulary)

Use these exact database-indexed words when constructing your search queries (`GET /catalog/search?q=<token>`) to avoid returning 0 results. This list represents the combined vocabulary of all 5 available SOR databases (Bihar, Karnataka, MP, Maharashtra, Rajasthan):

| Category | Real Database Search Tokens (Unified SOR Vocabulary) |
| :--- | :--- |
| **Concrete Grades** | `m10`, `m15`, `m20`, `m25`, `m30`, `m35`, `m40`, `m45`, `m50`, `m55`, `m60`, `m65`, `m70`, `m80`, `m90` |
| **Reinforcement & HTS** | `steel`, `hysd`, `tmt`, `rebar`, `rebars`, `bar`, `bars`, `wire`, `wires`, `strand`, `strands`, `high`, `tensile`, `prestressing`, `anchorage`, `fe`, `fe500`, `fe500d`, `fe550`, `fe550d`, `fe600m` |
| **Excavation & Foundations** | `excavation`, `excavated`, `excavator`, `earth`, `earthwork`, `soil`, `soils`, `clay`, `rock`, `rocks`, `boulder`, `boulders`, `well`, `wells`, `pile`, `piles`, `cap`, `caps`, `sinking`, `sandy`, `clayey` |
| **Bearings & Pedestals** | `bearing`, `bearings`, `pot`, `ptfe`, `elastomer`, `elastomeric`, `chloroprene`, `pedestal` |
| **Waterproofing & Asphalt** | `waterproof`, `waterproofing`, `bitumen`, `bitumenous`, `mastic`, `asphalt`, `asphaltic`, `wearing`, `coat`, `course`, `membrane`, `tar`, `vg`, `vg30`, `vg40` |
| **Expansion Joints** | `joint`, `joints`, `expansion`, `strip`, `seal`, `sealant`, `sealer`, `sealing`, `seals`, `filler`, `elastomeric` |
| **Railing & Barriers** | `railing`, `railings`, `crash`, `barrier`, `barriers`, `median`, `medians`, `divider`, `post`, `posts`, `pipe`, `pipes`, `gi`, `precast`, `rcc` |
| **Marking, Paint & Coatings** | `marking`, `paint`, `painting`, `enamel`, `synthetic`, `cement`, `corrosion`, `corrosive`, `anticorrosive`, `epoxy`, `coated`, `treatment`, `thermoplastic` |

---

## 8. Errors & Troubleshooting

Errors are returned as JSON: `{"error": "<code>", "details"?: [...], "documentation_url": "http://127.0.0.1:8765/help"}`. Every error links back to the live docs — follow that link rather than assuming this file is current.

| Status | Error code | Meaning | Resolution |
| :--- | :--- | :--- | :--- |
| 400 | `invalid_json_body` | Body missing or not a JSON object. | Send a JSON object as the request body. |
| 400 | `invalid_field_values` | One or more values don't match the field schema; nothing was applied. | Fix the fields listed in `"details"` against the GET response's `"fields"` schema. |
| 401 | `unauthorized` | Missing or incorrect `X-API-Token`. | See troubleshooting flow below. |
| 404 | `project_not_found` | No project with that id exists on this machine. | `GET /projects` for valid ids. |
| 404 | `project_not_open` | Project exists but isn't open in the app. | `POST /projects/open`, then retry once it's finished opening. |
| 404 | `not_found` | Unknown route or page name. | Check `"available_pages"` in the response and `GET /help`. |
| 404 | `not_supported` | Chunk doesn't support `add_from_catalog` (only `str_*` chunks do). | Use `POST /{project_id}/{chunk}` with `"catalog_item"` or `"values"` instead. |
| 423 | `project_locked` | Project is locked (a calculation completed and auto-locked it, or a human locked it manually). Every write endpoint, including `GET /validate`, is blocked while locked. | `POST /{project_id}/unlock`, then retry. |
| 403 | `denied` | User clicked Deny (or closed) the `/get_tokens` popup for this request. | Ask again for a fresh popup, or fall back to File > API Access. |
| 403 | `token_already_delivered` | `/get_tokens` already handed this project's token out once this session. | Ask the user for it via File > API Access instead — it won't be resent automatically. |
| 429 | `too_many_requests` | `/get_tokens` popup cap hit for this project this session. | Ask the user for it via File > API Access instead of retrying. |

**Troubleshooting flow:**
1. **401 Unauthorized** — First `GET /projects/active` (no token needed). If your project isn't in that list, its window was closed: tokens are cleared on close and a new one is generated on reopen, so the old one will never work again — `POST /projects/open`, then ask the user for the fresh token via File > API Access. If the project *is* listed, the token itself is stale or mistyped — ask the user for the current one.
2. **404 `project_not_open`** — `POST /projects/open`, then poll `GET /{project_id}/{page}` until it stops returning `project_not_open`.
3. **Connection refused / timeout** — The app isn't running, the local API is disabled in Settings, or it's listening on a different auto-incremented port. Try the next few ports, or ask the user to check File > API Access.
4. Tokens also reset on every app restart — a token that worked yesterday can 401 today if the app was restarted in between.

---

## 9. Quickstart

1. `GET http://127.0.0.1:8765/projects` — find your `project_id` (no token needed).
2. If the project isn't open yet: `POST http://127.0.0.1:8765/projects/open` with `{"project_id": "..."}`, then wait/poll until it is.
3. Get the project's API token: try `GET http://127.0.0.1:8765/{project_id}/get_tokens` first (a human clicks Allow/Deny in the app; expect it to block a bit). If that doesn't return a token for any reason (denied, already delivered, capped, or not open), fall back to asking a human for it via File > API Access.
4. `GET http://127.0.0.1:8765/{project_id}/{page}` with header `X-API-Token: <token>` — the response contains both the data and the full field schema (types, options, ranges, locked flags).
5. `POST` the same URL with only the fields you want to change — omitted fields keep their current value.