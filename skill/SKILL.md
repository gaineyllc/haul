---
name: haul
description: >
  Torrent hunter that searches IPTorrents, scores results by quality (2160p+HDR
  first, then seeder-balanced), and sends downloads to Synology Download Station.
  Use when the user asks to download, find, grab, or get a movie or TV show.
  Also handles all Download Station management: list/pause/resume/delete tasks,
  schedule, speed limits, RSS feeds, RSS auto-download filters, BT search, and
  file selection for multi-file torrents.
  Triggers on: "download [title]", "get me [show/movie]", "find [title]",
  "grab [show] season X episode Y", "what's downloading", "pause my downloads",
  "set up auto-download for [show]", "add RSS feed", "check download station".
  Requires haul MCP server running: uv run python -m src.mcp_server
  Project: F:\projects\haul
---

# haul Skill

Media acquisition agent. IPTorrents → Synology Download Station.

## Core workflow

**Always use haul_hunt for download requests.** It normalizes natural language,
scores by quality, and returns a confirmation gate before downloading.

```
User: "Download season 5 episode 1 of The Boys"
→ haul_hunt("Download season 5 episode 1 of The Boys")
→ Returns: awaiting_confirmation + recommended torrent + next_step hint
→ Present recommendation to user, ask to confirm
→ User confirms → haul_download(torrent_id=..., torrent_name=..., destination=...)
→ Returns: queued + destination folder
```

**Quality priority (built in — don't override unless asked):**
2160p + DV + HDR + Atmos > 2160p + HDR > 2160p > 1080p WEB-DL > 1080p

## Key tools

| Tool | When to use |
|---|---|
| `haul_hunt(query)` | Any download request — normalizes NL, scores, confirms |
| `haul_search(query)` | User wants to browse options without committing |
| `haul_download(torrent_id, torrent_name, destination)` | After confirmation |
| `haul_list_downloads()` | "What's downloading?" / progress check |
| `haul_pause/resume/delete_task(task_id)` | Task control |
| `haul_set_schedule_hours(start, end)` | "Only download overnight" |
| `haul_add_rss_filter(...)` | "Auto-download new episodes of X" |
| `haul_list_folders()` | Discover valid destination paths |
| `haul_setup_check()` | Diagnose connection issues |

## Query normalization (automatic)

haul understands natural language — pass it exactly as the user said it:
- "season 5 episode 1 of The Boys" → searches "The Boys S05E01"
- "the boys s5e1 4k" → searches "The Boys S05E01 2160p"
- "dune part two" → searches "Dune Part Two"
- "severance season 2" → searches "Severance S02" (season pack)

## Confirmation flow

haul_hunt always returns `awaiting_confirmation` by default.
Show the user:
- Selected title, resolution, HDR type, source, audio, size, seeders
- The `explanation` field showing why it was chosen over alternatives
- Ask: "Shall I download this?" → on yes, call haul_download()

To skip confirmation (trusted user, auto mode): `auto_confirm=True`

## Destinations

Folder routing is automatic. Override with `destination` param if needed.
To see available folders: `haul_list_folders()`

## Setup & credentials

Credentials stored PQC-encrypted at ~/.haul/credentials.enc
Setup: `uv run python -m src.haul.setup`
See `references/setup.md` for full credential list and troubleshooting.
