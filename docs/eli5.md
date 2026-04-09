# haul — Explained Simply

## What does haul do?

Imagine you want to watch a movie. Normally you'd have to:
1. Open a website
2. Search for the movie
3. Look through lots of results
4. Pick the best one
5. Download it
6. Wait for it to finish
7. Move it to the right folder

**haul does all of that for you automatically.** You just say:

> "Download The Boys Season 5 Episode 1"

And haul:
1. Understands what you mean (even if you say it in different ways)
2. Searches the internet for it
3. Looks at all the options and picks the best quality one (4K with HDR first, if available)
4. Downloads it to your TV/movie folder on your home server
5. Tells you it's done

---

## How does it understand me?

haul uses something called **natural language understanding**. That means it can figure out what you mean even when you say it differently:

| What you say | What haul searches for |
|---|---|
| "Download season 5 episode 1 of the boys" | The Boys S05E01 |
| "the boys s5e1 4k" | The Boys S05E01 2160p |
| "dune part two" | Dune Part Two |
| "severance season 2" | Severance S02 (whole season) |

---

## How does it pick the best version?

Think of it like buying a TV. There are lots of options at different prices and qualities. haul always tries to get you the best one it can, in this order:

```
🥇 4K + Dolby Vision + HDR  ← best possible picture
🥈 4K + HDR
🥉 4K (any)
4️⃣  1080p WEB-DL            ← really good
5️⃣  1080p
6️⃣  720p                    ← last resort
```

It also checks that enough people are sharing the file (called "seeders") — like making sure enough copies of a book are in the library before you try to borrow one.

---

## What is a "home server"?

haul is designed to work with a **Synology NAS** — that's like a little computer in your house that stores all your movies and TV shows. Think of it as your own personal Netflix server.

haul talks to it through something called the **Download Station API** — a special language your Synology NAS understands for telling it to download things.

---

## What is MCP?

MCP stands for **Model Context Protocol**. Big words, simple idea:

Imagine you have a really smart assistant (like an AI). The assistant is great at thinking and talking, but it can't actually *do* things — it can't click buttons, search websites, or talk to your TV server.

MCP is like giving that assistant a **toolbox**. Each tool does one specific thing:
- `haul_search` → search for a movie
- `haul_download` → download it
- `haul_list_downloads` → check what's downloading

When you talk to your AI assistant and say "download The Boys", the AI uses haul's tools through MCP to actually make it happen.

---

## How does it all connect?

```
You
 │
 │  "Download The Boys S05E01"
 ▼
AI Assistant (Claude, etc.)
 │
 │  uses MCP to call haul tools
 ▼
haul MCP Server (running on your computer)
 │
 ├──► IPTorrents (finds the torrent)
 │
 └──► Synology NAS (starts the download)
         │
         └──► Media/TV/ folder ✅
```

Everything happens automatically. You just ask, and it works.
