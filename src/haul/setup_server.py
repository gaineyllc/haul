"""
Haul Setup Server
─────────────────
Serves a local web form for credential setup when WinCred is missing or stale.
Integrated into the MCP server — no separate process needed.

Flow:
  1. MCP server starts
  2. Checks WinCred → if works, unlocks silently
  3. If not → serves http://localhost:8766/setup
  4. User enters passphrase in browser form
  5. Server validates, saves to WinCred, marks ready
  6. All MCP tools become available
"""
from __future__ import annotations

import asyncio
import os
import platform
from pathlib import Path
from typing import Any

# ── HTML for the setup page ────────────────────────────────────────────────────

SETUP_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🎣 haul setup</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0f0f0f; color: #e0e0e0;
    display: flex; align-items: center; justify-content: center;
    min-height: 100vh;
  }
  .card {
    background: #1a1a1a; border: 1px solid #2a2a2a;
    border-radius: 12px; padding: 40px; width: 420px;
    box-shadow: 0 20px 60px rgba(0,0,0,0.5);
  }
  h1 { font-size: 24px; margin-bottom: 8px; }
  .emoji { font-size: 32px; margin-bottom: 16px; display: block; }
  p { color: #888; font-size: 14px; margin-bottom: 24px; line-height: 1.6; }
  label { display: block; font-size: 13px; color: #aaa; margin-bottom: 8px; }
  input[type=password] {
    width: 100%; padding: 12px 16px; background: #111;
    border: 1px solid #333; border-radius: 8px;
    color: #e0e0e0; font-size: 15px; outline: none;
    transition: border-color 0.2s;
  }
  input[type=password]:focus { border-color: #4a9eff; }
  button {
    width: 100%; margin-top: 16px; padding: 13px;
    background: #4a9eff; color: #fff; border: none;
    border-radius: 8px; font-size: 15px; font-weight: 600;
    cursor: pointer; transition: background 0.2s;
  }
  button:hover { background: #3a8eef; }
  button:disabled { background: #333; color: #666; cursor: not-allowed; }
  .status {
    margin-top: 16px; padding: 12px 16px; border-radius: 8px;
    font-size: 13px; display: none;
  }
  .status.error { background: #2a1111; border: 1px solid #5a1111; color: #ff6b6b; display: block; }
  .status.success { background: #112a11; border: 1px solid #115a11; color: #6bff6b; display: block; }
  .status.loading { background: #111a2a; border: 1px solid #113a5a; color: #6baaff; display: block; }
  .lock { font-size: 13px; color: #555; margin-top: 20px; text-align: center; }
</style>
</head>
<body>
<div class="card">
  <span class="emoji">🎣</span>
  <h1>haul setup</h1>
  <p>Enter your credential store passphrase to unlock haul. This is saved securely
     in Windows Credential Manager — you won't be asked again.</p>
  <label for="pp">Passphrase</label>
  <input type="password" id="pp" placeholder="Enter passphrase" autofocus
         onkeydown="if(event.key==='Enter') unlock()">
  <button onclick="unlock()" id="btn">Unlock haul</button>
  <div class="status" id="status"></div>
  <p class="lock">🔒 Local only · never sent anywhere · stored in Windows Credential Manager</p>
</div>
<script>
async function unlock() {
  const pp = document.getElementById('pp').value;
  if (!pp) return;
  const btn = document.getElementById('btn');
  const status = document.getElementById('status');
  btn.disabled = true;
  btn.textContent = 'Unlocking…';
  status.className = 'status loading';
  status.textContent = 'Verifying passphrase…';
  try {
    const r = await fetch('/setup/unlock', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({passphrase: pp})
    });
    const data = await r.json();
    if (data.ok) {
      status.className = 'status success';
      status.textContent = '✅ ' + (data.message || 'Unlocked! haul is ready.');
      btn.textContent = 'Done';
      setTimeout(() => { window.close(); }, 2000);
    } else {
      status.className = 'status error';
      status.textContent = '✗ ' + (data.error || 'Wrong passphrase.');
      btn.disabled = false;
      btn.textContent = 'Try Again';
      document.getElementById('pp').value = '';
      document.getElementById('pp').focus();
    }
  } catch(e) {
    status.className = 'status error';
    status.textContent = '✗ Could not reach haul server.';
    btn.disabled = false;
    btn.textContent = 'Try Again';
  }
}
</script>
</body>
</html>
"""

READY_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>haul ready</title>
<style>
body { font-family: -apple-system, sans-serif; background: #0f0f0f; color: #e0e0e0;
  display:flex; align-items:center; justify-content:center; min-height:100vh; }
.card { background:#1a1a1a; border:1px solid #2a2a2a; border-radius:12px; padding:40px;
  text-align:center; }
h1 { color: #6bff6b; margin-top:12px; }
p { color:#888; margin-top:8px; font-size:14px; }
</style></head>
<body><div class="card">
<span style="font-size:48px">✅</span>
<h1>haul is ready</h1>
<p>MCP server is running. You can close this window.</p>
</div></body></html>
"""


# ── Setup state ────────────────────────────────────────────────────────────────

class SetupState:
    unlocked: bool = False
    needs_setup: bool = False

    @classmethod
    def check(cls) -> None:
        """Check WinCred and set state flags."""
        from src.haul.credentials import (
            load_passphrase_from_wincred, unlock_store,
            _Store, initialized, _Session
        )
        if not initialized():
            cls.needs_setup = True
            return

        if _Session.loaded():
            cls.unlocked = True
            return

        pp = load_passphrase_from_wincred()
        if pp:
            try:
                unlock_store(pp)
                cls.unlocked = True
                return
            except ValueError:
                # Stale WinCred — clear it
                _clear_wincred()

        cls.needs_setup = True

    @classmethod
    def open_setup_page(cls, port: int = 8766) -> None:
        """Open the setup page in the default browser."""
        import webbrowser
        url = f"http://localhost:{port}/setup"
        print(f"[haul] Setup required → opening {url}")
        webbrowser.open(url)


def _clear_wincred() -> None:
    try:
        import win32cred
        win32cred.CredDelete('haul-mcp-passphrase', win32cred.CRED_TYPE_GENERIC)
    except Exception:
        pass


# ── FastAPI routes to add to the MCP server ───────────────────────────────────

def register_setup_routes(mcp: Any) -> None:
    """
    Register /setup and /setup/unlock routes on a FastMCP instance.
    Uses mcp.custom_route() which is the FastMCP 3.x API.
    """
    from starlette.requests import Request
    from starlette.responses import HTMLResponse, JSONResponse, Response

    @mcp.custom_route("/setup", methods=["GET"])
    async def setup_page(request: Request) -> Response:
        if SetupState.unlocked:
            return HTMLResponse(READY_HTML)
        return HTMLResponse(SETUP_HTML)

    @mcp.custom_route("/setup/unlock", methods=["POST"])
    async def setup_unlock(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

        pp = body.get("passphrase", "")
        if not pp:
            return JSONResponse({"ok": False, "error": "Passphrase required"})

        from src.haul.credentials import (
            unlock_store, save_passphrase_to_wincred, initialized
        )

        try:
            if not initialized():
                return JSONResponse({
                    "ok": False,
                    "error": "Store not initialized. Run: uv run python -m src.haul.setup"
                })

            unlock_store(pp)

            if platform.system() == "Windows":
                save_passphrase_to_wincred(pp)

            SetupState.unlocked = True
            SetupState.needs_setup = False

            return JSONResponse({
                "ok": True,
                "message": "Passphrase saved to Windows Credential Manager. haul is ready."
            })

        except ValueError:
            return JSONResponse({"ok": False, "error": "Wrong passphrase — try again."})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)})

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> Response:
        return JSONResponse({"status": "ok", "unlocked": SetupState.unlocked})
