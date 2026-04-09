# haul

Torrent hunter for IPTorrents → Synology Download Station.

`npx haul "The Boys S05E01"`

[![MCP Compatible](https://img.shields.io/badge/MCP-compatible-blue)](https://modelcontextprotocol.io)
[![Python 3.14+](https://img.shields.io/badge/python-3.14+-green)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-69%20passing-brightgreen)](tests/)
[![Platforms](https://img.shields.io/badge/platforms-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)](#)

## Documentation

| | |
|---|---|
| [eli5.md](docs/eli5.md) | What haul does, explained simply |
| [how-mcp-works.md](docs/how-mcp-works.md) | What MCP is and why it exists |
| [architecture.md](docs/architecture.md) | How haul is built, every component |
| [code-review.md](docs/code-review.md) | Full code walkthrough for reviewers |
| [cross-platform.md](docs/cross-platform.md) | Setup on Windows, macOS, Linux |

## What it does

1. Searches IPTorrents for your query
2. Scores all results — **2160p + HDR first**, then balances quality vs seeder availability
3. Presents the selection for confirmation (or auto-downloads with `--yes`)
4. Sends the `.torrent` directly to Synology Download Station in the right folder

## Quality selection logic

Priority order:
1. **2160p + Dolby Vision + HDR** (highest tier)
2. **2160p + HDR10**
3. **2160p + WEB-DL** (no explicit HDR tag)
4. **2160p** (any source)
5. **1080p + WEB-DL** (fallback)

Within each tier, balances:
- Seeder count (availability)
- Source quality (AMZN/DSNP > generic WEB-DL > WEBRip)
- Audio (Atmos > TrueHD > DDP5.1)
- Completed count (trust signal)

Cams are always rejected.

## Setup

```bash
# 1. Install
git clone https://github.com/gaineyllc/haul
cd haul
uv sync
uv run playwright install chromium

# 2. Configure credentials (PQC encrypted)
python -m src.haul.setup

# 3. Run
python -m src.mcp_server          # MCP server (Claude Desktop / Claude Code)
python -m src.mcp_server --http   # HTTP/SSE on port 8766
npx haul "Dune Part Two"          # CLI
```

## Claude Desktop config

```json
{
  "mcpServers": {
    "haul": {
      "command": "npx",
      "args": ["haul"]
    }
  }
}
```

## MCP Tools

| Tool | Description |
|---|---|
| `haul_hunt` | Search + select + optionally queue |
| `haul_search` | Search only, returns ranked results |
| `haul_confirm` | Confirm a pending haul_hunt |
| `haul_list_downloads` | List Download Station tasks |
| `haul_setup_check` | Verify credentials and connectivity |

## Credentials

All credentials stored encrypted with ML-KEM-768 (NIST FIPS 203 PQC):
```bash
python -m src.haul.setup   # interactive setup
```

Stores: `IPTORRENTS_USER`, `IPTORRENTS_PASS`, `SYNOLOGY_HOST`, 
`SYNOLOGY_USER`, `SYNOLOGY_PASS`, `DS_DOWNLOAD_DIR_TV`, `DS_DOWNLOAD_DIR_MOVIES`

## License

MIT
