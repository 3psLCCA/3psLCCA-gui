# 3psLCCA MCP server

Lets an AI app (Claude Desktop, Claude Code, Cursor, ...) read and edit
3psLCCA projects through the app's local API.

It runs as a separate small program that the AI app starts. It talks only to
the 3psLCCA app on this computer (`127.0.0.1`), and only through the API.
The API's own protections (tokens, the Allow/Deny popup, its limits) apply
unchanged.

## Setup

1. Install the SDK (Python 3.10+). A separate virtual environment is best:

   ```
   python -m venv lcca_mcp/.venv
   lcca_mcp/.venv/Scripts/python -m pip install -r lcca_mcp/requirements.txt
   ```

2. In 3psLCCA, make sure the local API is turned on in **Settings** (API section), and open a project.

3. Add the server to your AI app.

   **Claude Code**

   ```
   claude mcp add 3pslcca -- "<full path>/lcca_mcp/.venv/Scripts/python.exe" "<full path>/lcca_mcp/server.py"
   ```

   **Claude Desktop** (`claude_desktop_config.json`)

   ```json
   {
     "mcpServers": {
       "3pslcca": {
         "command": "<full path>/lcca_mcp/.venv/Scripts/python.exe",
         "args": ["<full path>/lcca_mcp/server.py"]
       }
     }
   }
   ```

## Giving it access to a project

The AI calls `request_access`. The app then shows an Allow/Deny popup that
names the program asking (this server: `python.exe` with `lcca_mcp/server.py`
in its command line). Click **Allow** only if you just asked the AI to work
on this project.

On Allow, the app gives this server its own key, which:

- works **only for this server process**. If another program copies it, the
  app refuses it and shows the attempt under **File → API Access → Recent
  activity**;
- stays inside the server and is never shown to the AI;
- ends when the server stops, the project closes, or you click **Revoke**
  next to it in **File → API Access**. After that the AI asks again.

The app stops showing popups for a project after 3 that end without Allow,
until the project is reopened.

Changes made through the API flash in the project window's status bar, and
File → API Access lists every program you allowed plus recent activity.

**If the popup can't be used**, copy the *script token* from File → API Access
into the server's config:

```json
"env": { "LCCA_PROJECT_ID": "proj_...", "LCCA_API_TOKEN": "..." }
```

This token works from any program, and the config file stores it in plain
text, so prefer the popup.

## Backups

Before any tool that changes a page (`update_page`, `add_from_catalog`,
`add_manual`, `trash_entry`), the server reads the page and saves it to:

```
~/.3pslcca_mcp/backups/<project_id>/<page>/<UTC time>-<action>.json
```

If the backup can't be written, the change is not sent. `list_backups` and
`read_backup` let the AI show you an earlier version. There is no automatic
restore: the AI shows you the differences and re-applies old values with
`update_page` once you agree.

`validate_project` and `unlock_project` don't change inputs, so they make no
backup. `validate_project` locks the project when it calculates successfully.

## Settings

| Variable | Default | |
|---|---|---|
| `LCCA_API_PORT` | `8765` | The app's API port. |
| `LCCA_PROJECT_ID`, `LCCA_API_TOKEN` | – | A pasted token, see above. |
| `LCCA_BACKUP_DIR` | `~/.3pslcca_mcp/backups` | Where backups go. |

## Your responsibility

Project names and text fields are passed to the AI as they are. Text such as
"ignore your instructions and…" in a project could steer it. Check what the
AI changed in the app, and keep the backups until you're happy.

See `SKILLS/SKILL-3pslcca-mcp.md` for how the AI should use these tools.
