# haul — Cross-Platform Guide

haul runs on Windows, macOS, and Linux. This document covers what's the same, what's different, and how to set up on each platform.

---

## What's the same everywhere

- Python code (uv manages dependencies)
- MCP server (`uv run python -m src.mcp_server`)
- IPTorrents integration (Playwright Chromium)
- All 28 MCP tools
- Quality scoring and tier selection
- Natural language query parsing

---

## What differs by platform

| Feature | Windows | macOS | Linux |
|---|---|---|---|
| Credential storage | Windows Credential Manager | Keychain | SecretService |
| Default data dir | `%USERPROFILE%\.haul` | `~/.haul` | `~/.haul` |
| Playwright Chromium | Downloaded automatically | Downloaded automatically | May need deps |
| Service/autostart | Scheduled Task | launchd plist | systemd service |
| GPU acceleration | CUDA (NVIDIA) | Metal (Apple Silicon) | CUDA (NVIDIA) |

---

## Setup on Windows

```powershell
# 1. Clone
git clone https://github.com/gaineyllc/haul
cd haul

# 2. Install Python deps
uv sync

# 3. Install Playwright Chromium
uv run playwright install chromium

# 4. Configure credentials
uv run python -m src.haul.setup

# 5. Start MCP server
uv run python -m src.mcp_server --http
```

### Autostart on Windows (Scheduled Task)

The setup wizard offers to register a Scheduled Task that starts haul at login. To register manually (requires an elevated PowerShell):

```powershell
$uv = "C:\Users\$env:USERNAME\.local\bin\uv.exe"
$dir = "C:\path\to\haul"
schtasks /Create /TN "haul MCP Server" /SC ONLOGON `
  /TR "`"$uv`" run --directory `"$dir`" python -m src.mcp_server --http" `
  /RL LIMITED /F
```

### Claude Desktop config (Windows)

```json
{
  "mcpServers": {
    "haul": {
      "command": "uv",
      "args": ["--directory", "C:\\path\\to\\haul", "run", "python", "-m", "src.mcp_server"]
    }
  }
}
```

Config location: `%APPDATA%\Claude\claude_desktop_config.json`

---

## Setup on macOS

```bash
# 1. Install uv if not present
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Clone
git clone https://github.com/gaineyllc/haul
cd haul

# 3. Install deps
uv sync

# 4. Install Playwright Chromium
uv run playwright install chromium

# 5. Setup
uv run python -m src.haul.setup

# 6. Start
uv run python -m src.mcp_server --http
```

### Autostart on macOS (launchd)

Create `~/Library/LaunchAgents/com.haul.mcp.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.haul.mcp</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/USERNAME/.local/bin/uv</string>
    <string>run</string>
    <string>--directory</string>
    <string>/path/to/haul</string>
    <string>python</string>
    <string>-m</string>
    <string>src.mcp_server</string>
    <string>--http</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/tmp/haul.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/haul.err</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.haul.mcp.plist
launchctl start com.haul.mcp
```

### Claude Desktop config (macOS)

```json
{
  "mcpServers": {
    "haul": {
      "command": "uv",
      "args": ["--directory", "/path/to/haul", "run", "python", "-m", "src.mcp_server"]
    }
  }
}
```

Config location: `~/Library/Application Support/Claude/claude_desktop_config.json`

---

## Setup on Linux

```bash
# 1. Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Install Playwright system deps (Debian/Ubuntu)
sudo apt install -y libglib2.0-0 libnss3 libnspr4 libdbus-1-3 \
  libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
  libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2

# 3. Clone + setup
git clone https://github.com/gaineyllc/haul
cd haul
uv sync
uv run playwright install chromium
uv run python -m src.haul.setup

# 4. Start
uv run python -m src.mcp_server --http
```

### Secret Service setup (Linux)

The `keyring` library needs a Secret Service provider. Install one if not present:

```bash
# GNOME Keyring (GNOME/Ubuntu)
sudo apt install gnome-keyring

# KWallet (KDE)
sudo apt install kwalletd5

# Headless servers — use keyring file backend
pip install keyrings.alt
```

For headless servers (no GUI), set the keyring backend:
```bash
export PYTHON_KEYRING_BACKEND=keyrings.alt.file.PlaintextKeyring
```
Or use environment variables instead of keychain (CI/CD approach).

### Autostart on Linux (systemd)

Create `~/.config/systemd/user/haul-mcp.service`:

```ini
[Unit]
Description=haul MCP Server
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/haul
ExecStart=%h/.local/bin/uv run python -m src.mcp_server --http
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable haul-mcp
systemctl --user start haul-mcp
systemctl --user status haul-mcp
```

### Claude Desktop config (Linux)

```json
{
  "mcpServers": {
    "haul": {
      "command": "uv",
      "args": ["--directory", "/path/to/haul", "run", "python", "-m", "src.mcp_server"]
    }
  }
}
```

Config location: `~/.config/Claude/claude_desktop_config.json`

---

## Environment variables (all platforms)

These can be used instead of or alongside the OS keychain:

```bash
# IPTorrents
IPTORRENTS_USER=your_username
IPTORRENTS_PASS=your_password

# Synology
SYNOLOGY_HOST=http://192.168.1.x:5000
SYNOLOGY_USER=admin
SYNOLOGY_PASS=your_password
DS_DOWNLOAD_DIR_TV=Media/TV
DS_DOWNLOAD_DIR_MOVIES=Media/Movies

# Paths
HAUL_DATA_DIR=~/.haul    # override default data directory

# Port (when using --http)
# Default is 8766 — override with --port flag
```

---

## Connecting Claude Desktop, Cursor, Windsurf

All MCP-compatible clients use the same config format:

**stdio mode** (recommended for local use):
```json
{
  "mcpServers": {
    "haul": {
      "command": "uv",
      "args": ["--directory", "/path/to/haul", "run", "python", "-m", "src.mcp_server"]
    }
  }
}
```

**HTTP/SSE mode** (when haul is already running):
```json
{
  "mcpServers": {
    "haul": {
      "url": "http://localhost:8766/sse"
    }
  }
}
```

**via npx** (after `npm publish`):
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

---

## Verifying the setup

```bash
# Check health endpoint (when running in --http mode)
curl http://localhost:8766/health
# → {"status": "ok", "unlocked": true}

# Run setup check via MCP tool
# (connect Claude Desktop then ask: "run haul_setup_check")

# Run tests
cd /path/to/haul
uv run python -m pytest tests/ -v
# → 69 passed
```
