# How MCP Works

## The problem MCP solves

AI language models are powerful at reasoning but isolated. They can understand your request perfectly but can't actually *do* anything — they can't browse websites, download files, or talk to your home server. They're brains without hands.

Before MCP, every AI integration was custom-built. OpenAI had one way to add tools, Anthropic had another, Google had another. If you built a tool for Claude, it wouldn't work with GPT. Fragmentation everywhere.

**MCP (Model Context Protocol)** is an open standard created by Anthropic in late 2024 that gives AI models a universal way to use external tools. It's like USB — one standard that works everywhere.

---

## The three roles in MCP

```
┌─────────────┐       MCP Protocol        ┌─────────────┐
│  MCP Client │ ◄────────────────────────► │  MCP Server │
│  (AI Host)  │                            │  (Tools)    │
└─────────────┘                            └─────────────┘
      │                                           │
   Claude                                      haul
   Cursor                               (search, download,
   Windsurf                              manage DS tasks)
```

**MCP Host / Client** — the AI assistant that wants to use tools. Claude Desktop, Claude Code, Cursor, Windsurf, or any MCP-compatible client.

**MCP Server** — a process that exposes tools the AI can call. haul is an MCP server. It runs on your machine and exposes tools like `haul_search`, `haul_download`, etc.

**MCP Protocol** — the JSON-RPC based communication layer between them. Defined at [modelcontextprotocol.io](https://modelcontextprotocol.io).

---

## How a tool call works (step by step)

When you ask Claude "download The Boys S05E01":

```
1. You type:  "Download The Boys S05E01"

2. Claude thinks:
   "The user wants to download something.
    I have a haul_hunt tool available.
    I should call it."

3. Claude sends to MCP:
   {
     "method": "tools/call",
     "params": {
       "name": "haul_hunt",
       "arguments": {
         "query": "Download The Boys S05E01"
       }
     }
   }

4. haul MCP server receives the call,
   runs haul_hunt("Download The Boys S05E01"),
   searches IPTorrents, scores results, picks best

5. haul returns to Claude:
   {
     "status": "awaiting_confirmation",
     "recommended": {
       "name": "The Boys S05E01 2160p AMZN WEB-DL DV HDR...",
       "resolution": "2160p",
       "seeders": 433
     },
     "next_step": "Call haul_download(...) to proceed"
   }

6. Claude presents this to you:
   "I found: The Boys S05E01 2160p AMZN WEB-DL...
    Shall I download this?"

7. You say "yes"

8. Claude calls haul_download(torrent_id="...", ...)

9. haul downloads the .torrent, sends to Synology DS

10. Done.
```

---

## Transport modes

MCP supports two ways for the client and server to communicate:

### stdio (Standard I/O)
The client starts the server as a child process. They communicate through stdin/stdout pipes. This is the default for local setups.

```json
// Claude Desktop config
{
  "mcpServers": {
    "haul": {
      "command": "uv",
      "args": ["run", "python", "-m", "src.mcp_server"]
    }
  }
}
```

The client launches `uv run python -m src.mcp_server`, sends JSON over stdin, reads responses from stdout. Simple, no networking.

### SSE (Server-Sent Events)
The server runs as an HTTP server. Clients connect over HTTP. Good for remote access or multiple clients.

```bash
uv run python -m src.mcp_server --http
# Server runs at http://0.0.0.0:8766/sse
```

haul supports both. Use stdio for local Claude Desktop. Use SSE (`--http`) when you want to call haul tools from scripts or remote clients.

---

## Tool discovery

When an MCP client connects, it asks: "what tools do you have?" The server responds with a list of tool definitions:

```json
{
  "tools": [
    {
      "name": "haul_hunt",
      "description": "Search IPTorrents and queue download...",
      "inputSchema": {
        "type": "object",
        "properties": {
          "query": {"type": "string"},
          "auto_confirm": {"type": "boolean"}
        }
      }
    }
  ]
}
```

The AI reads these descriptions and knows when and how to use each tool. The descriptions are the "API documentation" the AI reads at runtime — this is why good tool descriptions matter enormously.

---

## Why MCP over custom integrations?

| | Custom integration | MCP |
|---|---|---|
| Works with Claude | ✅ | ✅ |
| Works with GPT | ❌ | ✅ |
| Works with Cursor | ❌ | ✅ |
| Works with future AIs | ❌ | ✅ |
| Standard protocol | ❌ | ✅ |
| Zero client code | ❌ | ✅ |

Build once, works everywhere. That's the MCP value proposition.

---

## haul's MCP server in one diagram

```
src/mcp_server.py
│
├── FastMCP("haul")          ← creates the server
│
├── @mcp.tool haul_search    ─► src/haul/agent.py::search()
├── @mcp.tool haul_download  ─► src/haul/agent.py::download()
├── @mcp.tool haul_hunt      ─► src/haul/agent.py::hunt()
│
├── @mcp.tool haul_list_downloads ─► src/haul/synology.py
├── @mcp.tool haul_pause_task     ─► src/haul/synology.py
│   ... (28 tools total)
│
├── /setup  (GET)  ─► setup_server.py::SETUP_HTML
├── /health (GET)  ─► {"status": "ok", "unlocked": true}
│
└── runs on stdio or SSE (:8766)
```
