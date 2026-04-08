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
def ask_bool(p, d=True): v=input(f"  {B}{p} {'[Y/n]' if d else '[y/N]'}: {R}").strip().lower(); return d if not v else v in("y","yes")


def main():
    print(f"\n{B}{C}╔══════════════════════════╗\n║  🎣 haul setup          ║\n╚══════════════════════════╝{R}\n")

    # Init credential store
    hdr("Step 1: Secure Credential Store (ML-KEM-768)")
    if _Store.initialized():
        ok("Credential store already initialized")
        unlock_store()
    else:
        print("  Creating PQC-encrypted credential store...\n")
        init_store()
        ok("Credential store created at ~/.haul/credentials.enc")

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
            info = r2.json().get("data",{})
            ok(f"Download Station version: {info.get('version','unknown')}")

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

    print(f"\n{B}{G}✅ haul setup complete!{R}")
    print(f"\n  Start MCP server:  {C}uv run python -m src.mcp_server{R}")
    print(f"  Test a hunt:       {C}python -m src.haul.cli \"The Boys S05E01\"{R}\n")


if __name__ == "__main__":
    main()
