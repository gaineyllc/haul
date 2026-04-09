# haul Architecture

## System overview

```
┌─────────────────────────────────────────────────────────┐
│                    haul MCP Server                       │
│                  src/mcp_server.py                       │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │   28 MCP     │  │  Setup UI    │  │   Health     │  │
│  │   Tools      │  │  /setup      │  │   /health    │  │
│  └──────┬───────┘  └──────────────┘  └──────────────┘  │
│         │                                               │
│  ┌──────▼───────────────────────────────────────────┐  │
│  │              Core Agent Layer                     │  │
│  │              src/haul/agent.py                    │  │
│  │                                                   │  │
│  │  search()    download()    hunt()                 │  │
│  └──────┬──────────────┬────────────────────────────┘  │
│         │              │                               │
│  ┌──────▼──────┐  ┌────▼──────────┐                  │
│  │  IPTorrents │  │   Synology    │                  │
│  │   Layer     │  │     Layer     │                  │
│  │  browser.py │  │  synology.py  │                  │
│  └──────┬──────┘  └────┬──────────┘                  │
│         │              │                               │
└─────────┼──────────────┼───────────────────────────────┘
          │              │
          ▼              ▼
    IPTorrents.com   Synology NAS
    (Playwright)     (HTTP API)
```

---

## Component deep-dive

### `src/mcp_server.py` — The entry point

The FastMCP server. Registers all 28 tools, handles startup, serves the `/setup` web UI and `/health` endpoint.

On startup:
1. Calls `SetupState.check()` — tries OS keychain silently
2. If credentials found → logs "Credentials loaded ✅"
3. If missing → opens `http://localhost:8766/setup` in browser
4. Registers setup routes (`/setup`, `/setup/unlock`, `/health`)
5. Starts FastMCP in stdio or SSE mode

**Key design decision:** The server auto-unlocks from the OS keychain. No passphrase prompts in production. If keychain is empty, the setup page handles it through a browser form — no terminal interaction required.

---

### `src/haul/agent.py` — The orchestrator

Contains the three core functions. Everything else is plumbing.

#### `search(query, min_seeders, prefer_4k_hdr)`

```
raw_query
    │
    ▼ normalize()          Parse natural language
parsed.search_string
    │
    ▼ IPTSession.search()  Playwright → IPTorrents
raw_results[]
    │
    ▼ title filter         Remove unrelated results (short titles)
    │
    ▼ select_best()        Quality tier fallback chain
(recommended, tier)
    │
    ▼ return dict          {status, recommended, quality_tier, results[]}
```

No side effects. Safe to call without triggering any downloads.

#### `download(torrent_id, torrent_name, destination, media_type)`

```
torrent_id
    │
    ▼ IPTSession            Playwright fetches .torrent bytes
torrent_bytes
    │
    ▼ DownloadStation       DS2 API: JSON-encoded multipart upload
result
    │
    ▼ return dict           {status: "queued", destination}
```

No searching. Takes a torrent ID and queues it. Clean separation from search.

#### `hunt(query, ...)` — Convenience wrapper

```
search() → awaiting_confirmation → (user says yes) → download()
```

With `auto_confirm=True`, skips the gate. Useful for bulk operations.

---

### `src/haul/quality.py` — The quality engine

The scoring and selection logic. The most opinionated part of haul.

#### Quality tiers (in priority order)
```python
QUALITY_TIERS = [
    {"name": "2160p DV+HDR", "test": lambda r: r.is_4k and r.has_dv and r.has_hdr},
    {"name": "2160p HDR",    "test": lambda r: r.is_4k and r.has_hdr},
    {"name": "2160p",        "test": lambda r: r.is_4k},
    {"name": "1080p WEB-DL", "test": lambda r: RES_1080.search(r.name) and SRC_WEB_DL.search(r.name)},
    {"name": "1080p",        "test": lambda r: RES_1080.search(r.name)},
    {"name": "720p",         "test": lambda r: RES_720.search(r.name)},
    {"name": "any",          "test": lambda r: True},
]
```

`select_best()` tries each tier in order and returns the first tier that has viable results. Within a tier, it picks the highest `quality_score`.

#### Scoring formula
```
score = resolution_tier (1000/400/100)
      + HDR bonus (DV: +150, HDR: +80)
      + source bonus (REMUX: +120, WEB-DL: +80, WEBRip: +40)
      + streaming source bonus (AMZN/DSNP/etc: +50)
      + audio bonus (Atmos: +40, DTS-HD: +25, DDP5.1: +15)
      + seeder logarithmic bonus (log10(seeders+1) * 33)
      + trust bonus (log10(completed+1) * 5)
      - cam penalty (-900)
      - dual/multi audio penalty (-20)
```

Cams are effectively eliminated. Seeder count is logarithmic — 100 seeders is meaningfully better than 10, but 10,000 vs 1,000 barely matters.

---

### `src/haul/query.py` — Natural language parser

Regex-based query normalization. No LLM — fast, deterministic, testable.

Key patterns:
- `season 5 episode 1` → `S05E01`
- `s5e1` → `S05E01`
- `4k` / `uhd` / `2160p` → `2160p` (quality hint)
- `in hdr` / `dolby vision` → `hdr_hint=True`
- Year extraction: `Hoppers 2026` → `search_str="Hoppers 2026"`
- Title filter: short titles (≤3 words) require all words to appear in result name

---

### `src/haul/browser.py` — IPTorrents session

Playwright persistent browser context. Login once, reuse forever.

Session stored at `~/.haul/session/storage.json` — survives process restarts. HttpOnly cookies (invisible to JS) are preserved because Playwright operates at the browser level, not the JS level.

Key design:
- `ensure_logged_in()` checks if session is valid before every search
- `search()` paginates up to `max_pages` to find all quality variants
- `download_torrent()` fetches the `.torrent` bytes using the authenticated session
- Result parsing uses `eval_on_selector_all` — executes JS in the browser to extract structured data from the DOM

---

### `src/haul/synology.py` — Download Station API client

Handles both DSM 6 (classic `task.cgi`) and DSM 7 (`entry.cgi` / DS2 API).

#### API discovery
On connect, queries `SYNO.API.Info` to discover what the NAS supports:
- If `SYNO.DownloadStation2.Task` exists → use DS2 / entry.cgi
- Otherwise → use classic DS1 / task.cgi

#### The DS2 file upload quirk (critical)
DS2 API requires multipart fields to be JSON-encoded **and** the torrent file field must be named `torrent`, not `file`:

```python
# WRONG (what everyone tries first):
files={"file": ("task.torrent", bytes, "application/x-bittorrent")}

# RIGHT (what DS2 actually expects):
files=[
    ("type",        (None, '"file"')),        # JSON-quoted
    ("file",        (None, '["torrent"]')),   # JSON array
    ("destination", (None, '"Media/TV"')),    # JSON-quoted
    ("create_list", (None, "false")),         # plain string, NOT JSON-quoted
    ("torrent",     ("task.torrent", bytes, "application/x-bittorrent")),
]
```

This quirk (discovered via N4S4/synology-api) is not documented by Synology. `create_list` specifically must NOT be JSON-quoted — quoting it causes DS to silently accept the request but create nothing.

#### Destination normalization
DS API expects paths relative to the share root, not the full volume path:
- `/volume1/Media/TV` → `Media/TV` ✅
- `Media/TV` → `Media/TV` ✅

`_normalize_destination()` handles both inputs.

---

### `src/haul/credentials.py` — OS keychain storage

Uses the `keyring` library which routes to the appropriate OS backend:

| OS | Backend |
|---|---|
| Windows | Windows Credential Manager |
| macOS | Keychain |
| Linux | SecretService (GNOME Keyring / KWallet) |

No custom encryption. No passphrase to manage. The OS handles all security. Credentials persist across reboots and process restarts automatically.

```python
set_credential("IPTORRENTS_USER", "myuser")   # stores in OS keychain
get_credential("IPTORRENTS_USER")              # reads from OS keychain
                                               # falls back to env var if not found
```

The env var fallback makes haul compatible with CI/CD pipelines that inject secrets via environment.

---

### `src/haul/setup_server.py` — Web-based credential setup

Serves a local setup page when credentials aren't configured. Uses FastMCP's `custom_route()` to add HTTP routes alongside MCP endpoints.

`SetupState.check()` on server startup:
1. Reads from OS keychain
2. If `IPTORRENTS_USER` found → `unlocked=True`, silent start
3. If not found → `needs_setup=True`, opens browser to `/setup`

The `/setup` page is a clean HTML form (no framework, ~100 lines of vanilla JS). Submits to `/setup/unlock` POST endpoint which stores credentials in the OS keychain.

---

## Data flow: complete end-to-end

```
User: "Download The Boys S05E01"
         │
         ▼
   AI calls haul_hunt("Download The Boys S05E01")
         │
         ▼
   agent.py::hunt()
         │
         ├── query.py::normalize("Download The Boys S05E01")
         │       returns: search_string="The Boys S05E01", media_type="tv"
         │
         ├── agent.py::search("The Boys S05E01")
         │       │
         │       └── browser.py::IPTSession.search("The Boys S05E01")
         │               │
         │               └── Playwright → https://iptorrents.com/t?q=The+Boys+S05E01&o=seeders
         │                       → parse 132 results
         │                       → filter by title match
         │                       → quality.py::select_best() → tier="2160p DV+HDR"
         │                       → returns recommended torrent
         │
         ├── returns {status:"awaiting_confirmation", recommended:{...}, quality_tier:"2160p DV+HDR"}
         │
   AI: "Found: The Boys S05E01 2160p AMZN WEB-DL DV HDR. Download?"
         │
   User: "yes"
         │
   AI calls haul_download(torrent_id="7340996", torrent_name="...", destination="Media/TV")
         │
         ▼
   agent.py::download()
         │
         ├── browser.py::IPTSession.download_torrent("7340996")
         │       └── Playwright → https://iptorrents.com/download.php/7340996/...
         │               → returns 8992 bytes of .torrent data
         │
         └── synology.py::DownloadStation.add_torrent_file(bytes, "Media/TV")
                 │
                 ├── auth: SYNO.API.Auth → sid
                 ├── API discovery: uses DS2/entry.cgi
                 └── POST entry.cgi with JSON-encoded multipart
                         → {"success": true, "task_id": ["dbid_95"]}
         │
         ▼
   returns {status:"queued", destination:"Media/TV"}
         │
   AI: "Queued ✅ — The Boys S05E01 2160p DV+HDR downloading to Media/TV"
```

Total time: ~20-30 seconds (dominated by Playwright browser startup + IPTorrents page load).
