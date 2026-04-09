"""
Haul interactive setup.
python -m src.haul.setup
"""
from __future__ import annotations
import getpass, sys
from src.haul.credentials import get_credential, set_credential, initialized

R="\033[0m"; B="\033[1m"; G="\033[32m"; Y="\033[33m"; C="\033[36m"
def ok(m):   print(f"  {G}✅{R} {m}")
def warn(m): print(f"  {Y}⚠️ {R} {m}")
def info(m): print(f"  {C}ℹ{R}  {m}")
def hdr(m):  print(f"\n{B}{C}{m}{R}\n{'─'*len(m)}")
def ask(p, d=""): v=input(f"  {B}{p}{f' [{d}]' if d else ''}: {R}").strip(); return v or d
def ask_secret(p): return getpass.getpass(f"  {B}{p}: {R}")
def ask_bool(p, d=True): v=input(f"  {B}{p} {'[Y/n]' if d else '[y/N]'}: {R}").strip().lower(); return d if not v else v in("y","yes")


def main():
    print(f"\n{B}{C}╔══════════════════════════╗\n║  🎣 haul setup          ║\n╚══════════════════════════╝{R}\n")

    # ── Step 1: Credentials ────────────────────────────────────────────────────
    hdr("Step 1: Credential Store")
    info("Credentials are stored in your OS keychain (Windows Credential Manager,")
    info("macOS Keychain, or Linux SecretService). No passphrase needed.\n")

    ipt_user = get_credential("IPTORRENTS_USER")
    ipt_pass = get_credential("IPTORRENTS_PASS")
    if ipt_user and ipt_pass:
        ok(f"IPTorrents credentials already configured ({ipt_user})")
        if ask_bool("Update IPTorrents credentials?", False):
            set_credential("IPTORRENTS_USER", ask("Username"))
            set_credential("IPTORRENTS_PASS", ask_secret("Password"))
            ok("IPTorrents updated")
    else:
        hdr("Step 2: IPTorrents Credentials")
        set_credential("IPTORRENTS_USER", ask("Username"))
        set_credential("IPTORRENTS_PASS", ask_secret("Password"))
        ok("IPTorrents credentials saved")

    # ── Step 2: Synology ───────────────────────────────────────────────────────
    syno_host = get_credential("SYNOLOGY_HOST")
    if syno_host:
        ok(f"Synology already configured ({syno_host})")
        if ask_bool("Update Synology credentials?", False):
            _setup_synology()
    else:
        hdr("Step 3: Synology NAS")
        _setup_synology()

    # ── Step 3: Verify ─────────────────────────────────────────────────────────
    hdr("Verification")
    _verify()

    print(f"\n{B}{G}✅ haul setup complete!{R}\n")
    print(f"  Start MCP server: {C}uv run python -m src.mcp_server --http{R}")
    print(f"  Reset all creds:  {C}uv run python -m src.haul.reset{R}\n")


def _setup_synology():
    syno_host = ask("DSM URL", "http://192.168.1.10:5000")
    syno_user = ask("Username", "admin")
    syno_pass = ask_secret("Password")

    print(f"\n  Testing connection to {syno_host}...")
    try:
        import httpx, warnings
        warnings.filterwarnings("ignore")
        r = httpx.get(f"{syno_host.rstrip('/')}/webapi/auth.cgi",
            params={"api":"SYNO.API.Auth","version":"3","method":"login",
                    "account":syno_user,"passwd":syno_pass,
                    "session":"DownloadStation","format":"cookie"},
            verify=False, timeout=5)
        data = r.json()
        if data.get("success"):
            ok("Connected to Synology DSM")
            sid = data["data"]["sid"]
            r2 = httpx.get(f"{syno_host.rstrip('/')}/webapi/DownloadStation/info.cgi",
                params={"api":"SYNO.DownloadStation.Info","version":"1",
                        "method":"getinfo","_sid":sid}, verify=False, timeout=5)
            ds_info = r2.json().get("data",{})
            ok(f"Download Station version: {ds_info.get('version','unknown')}")
            r3 = httpx.get(f"{syno_host.rstrip('/')}/webapi/entry.cgi",
                params={"api":"SYNO.FileStation.List","version":"2",
                        "method":"list_share","_sid":sid}, verify=False, timeout=5)
            shares = r3.json().get("data",{}).get("shares",[])
            if shares:
                print(f"\n  Available shared folders:")
                for s in shares:
                    print(f"    • {s['name']}")
        else:
            warn(f"Connection failed — saved anyway")
    except Exception as e:
        warn(f"Could not connect: {e} — saved anyway")

    set_credential("SYNOLOGY_HOST", syno_host)
    set_credential("SYNOLOGY_USER", syno_user)
    set_credential("SYNOLOGY_PASS", syno_pass)

    print()
    info("Enter paths relative to the shared folder (e.g. 'Media/TV' not '/volume1/Media/TV')")
    set_credential("DS_DOWNLOAD_DIR_TV",     ask("TV folder",     "Media/TV"))
    set_credential("DS_DOWNLOAD_DIR_MOVIES", ask("Movies folder", "Media/Movies"))
    set_credential("DS_DOWNLOAD_DIR_OTHER",  ask("Other folder",  "Media/"))
    ok("Synology configured")


def _verify():
    checks = {
        "IPTORRENTS_USER": "IPTorrents username",
        "IPTORRENTS_PASS": "IPTorrents password",
        "SYNOLOGY_HOST":   "Synology host",
        "SYNOLOGY_USER":   "Synology username",
        "SYNOLOGY_PASS":   "Synology password",
        "DS_DOWNLOAD_DIR_TV":     "TV folder",
        "DS_DOWNLOAD_DIR_MOVIES": "Movies folder",
    }
    all_ok = True
    for key, label in checks.items():
        val = get_credential(key)
        if val:
            ok(f"{label}: configured")
        else:
            warn(f"{label}: MISSING — run setup again")
            all_ok = False
    return all_ok


if __name__ == "__main__":
    main()
