# haul Setup & Credentials

## First-time setup

```bash
cd F:\projects\haul
uv sync
uv run playwright install chromium
uv run python -m src.haul.setup   # interactive — tests connections, lists NAS folders
```

## Required credentials

| Key | Description |
|---|---|
| `IPTORRENTS_USER` | IPTorrents username |
| `IPTORRENTS_PASS` | IPTorrents password |
| `SYNOLOGY_HOST` | DSM URL e.g. `http://192.168.1.x:5000` |
| `SYNOLOGY_USER` | DSM username |
| `SYNOLOGY_PASS` | DSM password |
| `DS_DOWNLOAD_DIR_TV` | e.g. `downloads/tv` (NOT /volume1/...) |
| `DS_DOWNLOAD_DIR_MOVIES` | e.g. `downloads/movies` |

**Important:** Destination paths must be relative to the shared folder root,
NOT the full volume path. `/volume1/downloads/tv` → `downloads/tv`.

## Manage credentials manually

```bash
python -m src.haul.credentials set SYNOLOGY_HOST
python -m src.haul.credentials list
python -m src.haul.credentials migrate   # import from .env
```

## Start MCP server

```bash
# stdio (Claude Desktop / Claude Code)
uv run python -m src.mcp_server

# HTTP/SSE on port 8766
uv run python -m src.mcp_server --http
```

## Claude Desktop config

```json
{
  "mcpServers": {
    "haul": {
      "command": "uv",
      "args": ["--directory", "F:\\projects\\haul", "run", "python", "-m", "src.mcp_server"]
    }
  }
}
```

## Troubleshooting

Run `haul_setup_check()` to verify:
- IPTorrents credentials present
- Synology DS reachable + authenticated
- Destination folders configured

Common errors:
- DS error 402: destination denied → check folder permissions in DSM
- DS error 403: destination doesn't exist → run `haul_list_folders()` to find valid paths
- IPT login failed → re-run setup, check credentials
- Playwright session expired → delete `~/.haul/session/storage.json`, re-run setup
