"""
Haul interactive setup — configures all credentials.
python -m src.haul.setup
"""
from __future__ import annotations
import getpass, sys
from src.haul.credentials import (
    init_store, set_credential, unlock_store, get_credential, _Store
)

R="\033[0m"; B="\033[1m"; G="\033[32m"; Y="\033[33m"; C="\033[36m"
def ok(m):   print(f"  {G}✅{R} {m}")
def warn(m): print(f"  {Y}⚠️ {R} {m}")
def hdr(m):  print(f"\n{B}{C}{m}{R}\n{'─'*len(m)}")
def ask(p, d=""): v=input(f"  {B}{p}{f' [{d}]' if d else ''}: {R}").strip(); return v or d
def ask_secret(p): return getpass.getpass(f"  {B}{p}: {R}")
def info(m):  print(f"  {C}ℹ{R}  {m}")
def ask_bool(p, d=True): v=input(f"  {B}{p} {'[Y/n]' if d else '[y/N]'}: {R}").strip().lower(); return d if not v else v in("y","yes")


def main():
    print(f"\n{B}{C}╔══════════════════════════╗\n║  🎣 haul setup          ║\n╚══════════════════════════╝{R}\n")

    # Init credential store
    hdr("Step 1: Secure Credential Store (ML-KEM-768)")
    import platform as _platform
    from src.haul.credentials import load_passphrase_from_wincred, save_passphrase_to_wincred

    def _try_unlock_wincred():
        """Try to unlock using WinCred passphrase. Returns True on success."""
        pp = load_passphrase_from_wincred()
        if pp is None:
            return False
        try:
            unlock_store(pp)
            return True
        except ValueError:
            # WinCred passphrase is stale — clear it
            try:
                import win32cred
                win32cred.CredDelete('haul-mcp-passphrase', win32cred.CRED_TYPE_GENERIC)
            except Exception:
                pass
            return False

    def _unlock_interactive_and_save():
        """Prompt for passphrase, unlock, save to WinCred."""
        for attempt in range(3):
            try:
                unlock_store()  # prompts
                # Save to WinCred for future auto-unlock
                if _platform.system() == "Windows":
                    from src.haul.credentials import _Session
                    import getpass as _gp
                    pp = _gp.getpass("  Re-enter passphrase to save for auto-unlock: ")
                    try:
                        unlock_store(pp)  # verify
                        save_passphrase_to_wincred(pp)
                        ok("Passphrase saved to Windows Credential Manager")
                    except ValueError:
                        warn("Passphrase didn't match — not saved to WinCred")
                return True
            except ValueError:
                warn(f"Wrong passphrase (attempt {attempt+1}/3)")
        return False

    if not _Store.initialized():
        # Brand new setup
        print("  Creating PQC-encrypted credential store...\n")
        init_store()  # prompts for passphrase + confirm
        ok("Credential store created")
        if _platform.system() == "Windows":
            from src.haul.credentials import _Session
            import getpass as _gp
            pp = _gp.getpass("  Re-enter passphrase to save for auto-unlock: ")
            save_passphrase_to_wincred(pp)
            ok("Passphrase saved to Windows Credential Manager")
    elif _try_unlock_wincred():
        # Already unlocked via WinCred — nothing to do
        ok("Credential store unlocked automatically")
    else:
        # Store exists but WinCred is missing or stale — prompt once
        warn("Passphrase needed (WinCred not set or stale)")
        if not _unlock_interactive_and_save():
            warn("Could not unlock. Resetting credential store.")
            from pathlib import Path
            import os
            data_dir = Path(os.getenv('HAUL_DATA_DIR', str(Path.home() / '.haul')))
            for fname in ['credentials.enc', 'credentials.key']:
                p = data_dir / fname
                if p.exists(): p.unlink()
            from src.haul.credentials import _Session
            _Session.reset()
            _Store._cache = None
            init_store()
            ok("Credential store reset and recreated")

    # IPTorrents
    hdr("Step 2: IPTorrents Credentials")
    ipt_user = ask("IPTorrents username")
    ipt_pass = ask_secret("IPTorrents password")
    set_credential("IPTORRENTS_USER", ipt_user)
    set_credential("IPTORRENTS_PASS", ipt_pass)
    ok("IPTorrents credentials saved")

    # Synology
    hdr("Step 3: Synology NAS")
    syno_host = ask("DSM URL (e.g. http://192.168.1.x:5000)")
    syno_user = ask("DSM username", "admin")
    syno_pass = ask_secret("DSM password")

    # Test connection
    print(f"\n  Testing connection to {syno_host}...")
    try:
        import httpx, warnings; warnings.filterwarnings("ignore")
        r = httpx.get(f"{syno_host.rstrip('/')}/webapi/auth.cgi",
            params={"api":"SYNO.API.Auth","version":"3","method":"login",
                    "account":syno_user,"passwd":syno_pass,
                    "session":"DownloadStation","format":"cookie"},
            verify=False, timeout=5)
        data = r.json()
        if data.get("success"):
            ok(f"Connected to Synology DSM")
            sid = data["data"]["sid"]
            # Get DS info
            r2 = httpx.get(f"{syno_host.rstrip('/')}/webapi/DownloadStation/info.cgi",
                params={"api":"SYNO.DownloadStation.Info","version":"1",
                        "method":"getinfo","_sid":sid}, verify=False, timeout=5)
            ds_info = r2.json().get("data",{})
            ok(f"Download Station version: {ds_info.get('version','unknown')}")

            # List shared folders to help pick destination
            r3 = httpx.get(f"{syno_host.rstrip('/')}/webapi/entry.cgi",
                params={"api":"SYNO.FileStation.List","version":"2",
                        "method":"list_share","_sid":sid}, verify=False, timeout=5)
            shares = r3.json().get("data",{}).get("shares",[])
            if shares:
                print(f"\n  Available shared folders:")
                for s in shares:
                    print(f"    • {s['name']}  ({s.get('path','')})")
        else:
            code = data.get("error",{}).get("code","?")
            warn(f"Connection failed (error {code}) — saved anyway, check credentials")
    except Exception as e:
        warn(f"Could not connect: {e} — credentials saved, verify manually")

    set_credential("SYNOLOGY_HOST", syno_host)
    set_credential("SYNOLOGY_USER", syno_user)
    set_credential("SYNOLOGY_PASS", syno_pass)

    # Download destinations
    hdr("Step 4: Download Destinations")
    print("  Enter paths relative to the shared folder root.")
    print("  Example: 'downloads/tv'  (NOT '/volume1/downloads/tv')\n")
    tv_dir  = ask("TV show destination",  "downloads/tv")
    mov_dir = ask("Movies destination",   "downloads/movies")
    oth_dir = ask("Other destination",    "downloads/other")

    set_credential("DS_DOWNLOAD_DIR_TV",     tv_dir)
    set_credential("DS_DOWNLOAD_DIR_MOVIES", mov_dir)
    set_credential("DS_DOWNLOAD_DIR_OTHER",  oth_dir)
    ok("Download destinations saved")

    # ── Step 5: Windows service ────────────────────────────────────────────
    import platform
    if platform.system() == "Windows":
        hdr("Step 5: Run as Windows Service")
        print("  Running haul as a background service means it's always available")
        print("  for OpenClaw and Claude Desktop without manually starting it.\n")
        if ask_bool("Install haul MCP server as a Windows Scheduled Task?", True):
            _install_windows_service()

    print(f"\n{B}{G}✅ haul setup complete!{R}")
    print(f"\n  Start MCP server:  {C}uv run python -m src.mcp_server{R}")
    print(f"  Test a hunt:       {C}uv run python -m src.haul.cli \"The Boys S05E01\"{R}\n")


def _install_windows_service():
    """Register haul MCP server as a Windows Scheduled Task that starts at login."""
    import subprocess, sys
    from pathlib import Path

    here = Path(__file__).parent.parent.parent  # F:\haul-app
    uv = _find_uv()
    task_name = "haul MCP Server"

    # Build the XML task definition
    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>haul MCP Server — IPTorrents torrent hunter for Synology</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger><Enabled>true</Enabled></LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
    <Enabled>true</Enabled>
  </Settings>
  <Actions>
    <Exec>
      <Command>{uv}</Command>
      <Arguments>run python -m src.mcp_server --http</Arguments>
      <WorkingDirectory>{here}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""

    import tempfile, os
    tmp = tempfile.NamedTemporaryFile(suffix='.xml', delete=False, mode='w', encoding='utf-16')
    tmp.write(xml)
    tmp.close()

    try:
        result = subprocess.run(
            ['schtasks', '/Create', '/TN', task_name,
             '/XML', tmp.name, '/F'],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            ok(f'Scheduled Task registered: "{task_name}" (starts at login)')
            info('The MCP server will start automatically next time you log in.')
            info('For now, start it manually with the command below.')
        else:
            warn(f'Task registration failed: {result.stderr.strip()}')
            warn('You may need to run setup as Administrator for this step')
            print(f'  Manual command: {uv} run python -m src.mcp_server')
    except Exception as e:
        warn(f'Could not create scheduled task: {e}')
    finally:
        os.unlink(tmp.name)


def _find_uv() -> str:
    import shutil, os
    from pathlib import Path
    candidates = [
        Path(os.getenv('LOCALAPPDATA', '')) / 'Programs' / 'uv' / 'uv.exe',
        Path.home() / '.local' / 'bin' / 'uv.exe',
        Path.home() / '.local' / 'bin' / 'uv',
    ]
    for c in candidates:
        if c.exists(): return str(c)
    found = shutil.which('uv')
    return found or 'uv'


if __name__ == "__main__":
    main()
