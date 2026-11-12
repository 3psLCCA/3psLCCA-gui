---
name: 3pslcca-mcp
description: How to work on 3psLCCA projects through the 3pslcca MCP server tools (read_page, update_page, catalog_search, ...).
---

# 3psLCCA through MCP

The `3pslcca` MCP server wraps the app's local HTTP API. **All the rules in
`SKILL-3pslcca-local-api.md` still apply.** In particular: never assume a
value, always ask the user, and read a catalog item's description before you
suggest it. For finding SOR items, follow `SKILL-search-sor.md`. This file
only explains how the tools map to that guide.

> **SOR database, strict:** before reading or searching any material, confirm
> with the user which SOR database to use (`general_info` → `sor_database`).
> Never guess it. You may suggest one, but set it only after the user names
> that exact database or says yes to it. "Decide yourself", "full permission"
> or a region name alone is not a choice. Search only that database: `catalog_search`, `catalog_items`
> and `catalog_tokens` require its `db_key`. Never take a material from another
> database just to finish the task. If the item isn't there, stop and ask the
> user.

> **Where to add, strict:** "structure works" means one of four pages:
> Foundation (`str_foundation`), Sub Structure (`str_sub_structure`), Super
> Structure (`str_super_structure`) or Miscellaneous (`str_misc`). Before
> adding a material, ask the user which page and which component, unless they
> already said. Never pick them yourself.

## Tool ↔ API map

| Tool | API |
|---|---|
| `api_help` | `GET /help` |
| `list_projects(open_only, name_contains, limit)` | `GET /projects` or `/projects/active` (newest first, 20 by default) |
| `new_project_options`, `create_project` | `GET`/`POST /projects/new` |
| `open_project` | `POST /projects/open` |
| `request_access` | `POST /{id}/get_tokens` (popup) |
| `read_page` | `GET /{id}/{page}` |
| `update_page` | `POST /{id}/{page}` |
| `add_from_catalog`, `add_manual` | `POST /{id}/{page}/add_from_catalog` / `add_manual` |
| `list_trash`, `trash_entry` | `GET`/`POST /{id}/{page}/trash` |
| `validate_project` | `GET /{id}/validate` (locks on success) |
| `unlock_project` | `POST /{id}/unlock` |
| `catalog_*` | `GET /catalog/...` |
| `list_backups`, `read_backup` | local backup files |

Each tool returns `{"ok", "status", "body"}`: the HTTP status and the API's
JSON reply. On `ok: false`, read `body.error` and `body.message`, and follow
the troubleshooting table in the API guide.

## Access

1. `access_status` shows which projects you already have access to.
2. If you don't have access, tell the user a popup will appear in the app,
   then call `request_access` **once**. Never retry it in a loop: after 3
   popups without Allow the app stops showing them for that project.
3. If it fails, tell the user the reason (`denied`, `too_many_requests`,
   `popup_rate_limited`, `prompt_already_open`, `caller_unidentified`). As a
   fallback the user can put the script token from **File → API Access** into
   the server's config (`LCCA_PROJECT_ID`, `LCCA_API_TOKEN`) and restart it.
4. A tool returning 401 means access ended (revoked, project closed, app
   restarted). Tell the user; call `request_access` again only if they agree.
5. You never see the key. Don't ask the user to paste a token into the chat.

## Changing data

1. `read_page` first. The reply holds the data and the field schema.
2. Agree the exact change with the user.
3. Call the write tool. The server backs the page up first, and the result's
   `backup_file` names the backup. Mention it to the user.
4. `read_page` again to confirm the change, and show it to the user.

If a change went wrong: `list_backups`, then `read_backup`, then show the
user the old and new values, and re-apply the old ones with `update_page`
once they agree. Updates merge, so for table pages you may need
`trash_entry` to remove an entry that was added.

## Before these tools, tell the user

- `validate_project`: on success it **locks** the project against edits.
- `unlock_project`: clears the calculated results.
- `create_project`: country, currency and unit system are permanent.
