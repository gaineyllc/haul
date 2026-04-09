# haul — Code Review Guide

A complete walkthrough of every file, every non-obvious decision, and every place where things could go wrong. Written for the engineer doing the review.

---

## Repository structure

```
haul/
├── src/
│   ├── mcp_server.py          Entry point. 28 MCP tools + HTTP routes.
│   └── haul/
│       ├── agent.py           Core orchestration: search(), download(), hunt()
│       ├── browser.py         IPTorrents Playwright session
│       ├── credentials.py     OS keychain wrapper (keyring library)
│       ├── quality.py         Scoring engine + tier selection
│       ├── query.py           Natural language → search string parser
│       ├── reset.py           CLI credential reset utility
│       ├── setup.py           Interactive setup CLI
│       ├── setup_server.py    Web-based setup UI + MCP HTTP routes
│       └── synology.py        Synology Download Station API client
├── tests/
│   ├── test_agent.py          Agent confirm gate, dry run, no-results
│   ├── test_credentials.py    Keychain env fallback, noop unlock
│   ├── test_quality.py        Scoring, tier selection, explain
│   ├── test_query.py          NL parsing: episodes, seasons, quality hints
│   └── test_synology.py       Destination normalization, routing
├── skill/                     OpenClaw AgentSkill
│   ├── SKILL.md
│   └── references/
├── bin/haul.js                npm launcher (npx haul)
├── docs/                      You are here
├── pyproject.toml
└── package.json
```

---

## `src/mcp_server.py`

**What it does:** Creates the FastMCP server, registers all tools, wires up setup routes, handles startup.

**Key decisions:**

`SetupState.check()` is called at module import time (line ~20), not inside `__main__`. This means the credential check happens regardless of transport mode. Side effect: importing mcp_server in tests also runs credential check. Mitigated by keyring returning cleanly when no credentials are set.

Tools are registered with `@mcp.tool` decorator. FastMCP reads the function signature and docstring to generate the tool schema. **The docstring IS the API documentation the AI sees** — every parameter description matters.

The `--http` flag runs SSE transport on port 8766. The browser auto-open for setup only happens in `--http` mode because stdio mode has no web server to open.

**Watch for:** Tool docstrings that are vague or missing parameters. The AI will misuse tools it doesn't understand.

---

## `src/haul/agent.py`

**What it does:** Three functions — `search`, `download`, `hunt`. Nothing else.

**Key decisions:**

`search()` and `download()` are intentionally separate primitives. `hunt()` is a convenience wrapper. This separation matters for bulk operations — when downloading a full season, you call `search()` once and `download()` six times, not `hunt()` six times (which would search six times).

The title filter for short queries (≤3 words):
```python
if title_words and len(title_words) <= 3:
    filtered = [r for r in raw_results if _title_match(r)]
    if filtered:  # only apply if results remain
        raw_results = filtered
```
The `if filtered` guard is critical — without it, a misspelled short title would return zero results instead of falling back to the unfiltered set.

`asyncio.run()` is called in each MCP tool wrapper in `mcp_server.py`. This works because FastMCP runs tool calls in threads, not in an async event loop. If FastMCP ever switches to async tool execution, these will need to change to `await`.

**Watch for:** The browser session needs to be authenticated before search. `ensure_logged_in()` handles this but it requires the IPTorrents credentials to be in the keychain. If they're not there, `get_credential()` returns `None` and the error message tells the user to run setup — verify this path works cleanly.

---

## `src/haul/browser.py`

**What it does:** Manages a persistent Playwright browser session for IPTorrents.

**Key decisions:**

Persistent context (`storage_state`) saves session cookies across process restarts. Location: `~/.haul/session/storage.json`. IPTorrents uses HttpOnly cookies — invisible to JavaScript but preserved by Playwright's browser-level cookie management.

`_parse_results()` uses `eval_on_selector_all` to run JavaScript in the browser context to extract torrent data. This is more reliable than Python-side DOM parsing because IPTorrents renders some content dynamically.

The result parser extracts: name, torrent_id, download_url, size, seeders, leechers, completed count. Seeders and leechers are in the last two numeric cells of each row — the parser counts backward from the end of the cell list, which is fragile but matches the observed HTML structure.

**Watch for:** IPTorrents DOM changes will break `_parse_results()`. The `eval_on_selector_all` JavaScript uses `innerText` parsing which is sensitive to whitespace. The `filter()` for `torrent_id` guards against partial rows but doesn't handle all edge cases.

Age parsing (`_parse_age`) handles "hours", "days", "weeks", "minutes" but not "months" or "years" — returns 0.0 for those. This only affects the `age_hours` field, not selection logic, so it's cosmetic.

---

## `src/haul/quality.py`

**What it does:** Scores torrents and selects the best one using a tiered fallback chain.

**Key decisions:**

`select_best()` returns a tuple `(TorrentResult | None, str)` — the chosen torrent and the tier name. Callers must unpack both. This is a breaking API change from the original single-value return — tests confirm it.

The scoring formula uses logarithmic seeder weighting: `log10(seeders+1) * 33`. This means:
- 1 seeder: +10 points
- 10 seeders: +33 points
- 100 seeders: +66 points
- 1000 seeders: +99 points

The diminishing returns prevent a 5000-seeder 1080p from beating a 100-seeder 2160p — which is the correct behavior.

CAM penalty is -900. With the highest possible quality score (~1500), a cam could theoretically score around 600 — still less than a 1080p WEB-DL (~500 + seeder bonus). In practice, cams never win. The only exception would be a cam with 10,000+ seeders, but cams rarely have that.

**Watch for:** `Q_4K` regex matches "4K", "4096", "2160p", "UHD". If a title contains these as part of a show name (unlikely but possible), it would incorrectly classify it as 4K. The `is_4k` property on `TorrentResult` uses this regex on the full torrent name.

---

## `src/haul/query.py`

**What it does:** Parses natural language media queries into structured search strings.

**Key decisions:**

Pure regex — no ML. Fast (~1ms), deterministic, fully testable. The tradeoff is coverage: unusual phrasings won't be caught. The 27 passing tests cover the common cases.

Episode extraction tries patterns in order: long form first (`season X episode Y`), then short form (`SxxExx`), then alternate (`XxYY`). Only the first match is used — this prevents "S01E02" in a show name from being misinterpreted when the query also has "season 3 episode 4".

Year extraction uses `\b(19|20)\d{2}\b` which matches 1900-2099. Years in this range in the query are appended to the search string for disambiguation. Years stripped from the title prevent "Hoppers 2026" from becoming the title "Hoppers 2026" in the search — it becomes "Hoppers 2026" (year appended separately but effectively the same string in this case).

Title casing has a `LOWER_WORDS` set for articles and prepositions. "The Last of Us" capitalizes correctly. Edge case: "of" in show names will always be lowercase — "Band of Brothers" → "Band of Brothers" (correct). "Fear of the Walking Dead" → "Fear of the Walking Dead" (correct).

**Watch for:** The noise word stripping uses `\b` word boundaries. "download" as part of a show name ("Download This") would be stripped. Unlikely in practice.

---

## `src/haul/synology.py`

**What it does:** Complete Synology Download Station API client supporting DS1 (task.cgi) and DS2 (entry.cgi).

**Key decisions:**

**The DS2 multipart quirk** (most important thing to understand in this file):

DS2 requires field values to be JSON-encoded strings in multipart forms. This is undocumented by Synology. The fields that need JSON encoding: `type`, `file`, `destination`. The field that must NOT be JSON-encoded: `create_list`. The file field must be named `torrent` (not `file`). Discovered via [N4S4/synology-api](https://github.com/N4S4/synology-api).

```python
# Correct DS2 multipart structure:
files=[
    ("type",        (None, '"file"')),        # JSON string
    ("file",        (None, '["torrent"]')),   # JSON array
    ("destination", (None, f'"{dest}"')),     # JSON string
    ("create_list", (None, "false")),         # plain string
    ("torrent",     ("name.torrent", bytes, "application/x-bittorrent")),
]
```

If `create_list` is JSON-quoted as `'"false"'`, the request succeeds (HTTP 200, `success: true`) but creates a "list" object with no `task_id`, which DS silently discards. The task never appears in DS. This is the most subtle bug in the codebase.

**API discovery** at connect time queries `SYNO.API.Info` to find supported APIs. Prefers DS2 when available. The `_discover_api()` method has a fallback to defaults if the query fails — this means it degrades gracefully on unusual NAS configurations.

**Destination normalization** strips `/volume1/`, `/volume2/`, etc. prefixes and backslashes. The DS API expects share-relative paths (`Media/TV`) not volume-absolute paths (`/volume1/Media/TV`). The mixin classes in `synology_full.py` inherit from the main `DownloadStation` class and add the extended API methods.

**Watch for:** The `_sid` in the `disconnect()` method is set to `None` before the logout call. If the logout request itself fails, `_sid` is already `None`, so retry logic can't be added without restructuring. This is a minor resource leak but not a correctness issue.

---

## `src/haul/credentials.py`

**What it does:** Thin wrapper around the `keyring` library for OS keychain storage.

**Key decisions:**

`get_credential()` falls back to `os.getenv()` when the keychain returns nothing. This makes haul work in CI/CD pipelines where secrets are injected via environment variables without needing to set up the keychain.

`unlock_store()` is a no-op. It exists for API compatibility with the previous PQC-based implementation which required explicit unlocking. Callers that call `unlock_store()` still work — they just do nothing.

`_index_path()` maintains a JSON file listing known credential keys. This exists because `keyring` has no "list all credentials for service X" API — it can only get/set/delete individual keys by name. The index file bridges this gap.

**Watch for:** The index file at `~/.haul/credential_keys.json` can get out of sync if credentials are deleted through the OS UI rather than through haul. `list_credentials()` would then return stale keys. This is cosmetic — `get_credential()` would return `None` for a stale key, which is handled.

---

## Tests

### What's tested
- `test_quality.py` (19 tests): Scoring math, tier selection, cam rejection, seeder threshold, explain output
- `test_query.py` (27 tests): All NL patterns — long/short form episodes, seasons, quality hints, noise stripping, title casing
- `test_synology.py` (11 tests): Destination normalization, TV/movie routing heuristics
- `test_agent.py` (5 tests): Confirm gate behavior, dry run, auto-confirm, no-results case
- `test_credentials.py` (5 tests): Env fallback, noop unlock, session always loaded

### What's NOT tested (integration tests would cover these)
- Actual IPTorrents login and search (requires live session)
- Actual DS API calls (requires live NAS)
- Playwright browser lifecycle
- MCP tool schema validation

### Running tests
```bash
uv run python -m pytest tests/ -v
```

All 69 tests run in under 1 second — no network calls, no browser, pure logic.

---

## Known issues and limitations

1. **Playwright cold start**: First search in a new process takes 15-25 seconds to start Chromium. Subsequent searches reuse the browser. Persistent session file reduces login overhead.

2. **IPTorrents DOM dependency**: If IPTorrents changes their HTML structure, `_parse_results()` breaks. No API fallback — scraping is the only option for this private tracker.

3. **Single concurrent search**: The browser session is not thread-safe. Concurrent `haul_hunt` calls would race. In practice, MCP clients call tools sequentially so this hasn't been an issue.

4. **DS task deduplication**: Submitting the same torrent twice creates duplicate tasks in DS. haul doesn't check if a torrent is already downloading before adding it.

5. **No retry logic**: If the DS API call fails transiently, the download is lost. No retry or queue persistence.
