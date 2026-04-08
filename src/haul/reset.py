"""
haul credential reset — wipes and rebuilds everything in sync.
Fixes WinCred/keyfile mismatch that can occur after interrupted setup.

Usage:
  uv run python -m src.haul.reset
"""
from __future__ import annotations
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

R="\033[0m"; B="\033[1m"; G="\033[32m"; Y="\033[33m"; C="\033[36m"
def ok(m):   print(f"  {G}✅{R} {m}")
def warn(m): print(f"  {Y}⚠️ {R} {m}")
def ask(p, d=""): v=input(f"  {B}{p}{f' [{d}]' if d else ''}: {R}").strip(); return v or d
def ask_secret(p): return getpass.getpass(f"  {B}{p}: {R}")


def run_reset(silent: bool = False) -> None:
    """
    Wipe credential store + WinCred and rebuild everything in sync.
    silent=True skips confirmation prompt (for use from setup).
    """
    if not silent:
        print(f"\n{B}{C}╔══════════════════════════════╗")
        print(f"║  🔑 haul credential reset    ║")
        print(f"╚══════════════════════════════╝{R}\n")
        print("  This will wipe your credential store and WinCred entry,")
        print("  then rebuild them in sync. Your credentials will be re-entered.\n")
        confirm = input(f"  {B}Continue? [Y/n]: {R}").strip().lower()
        if confirm not in ("", "y", "yes"):
            print("  Cancelled.")
            return

    # ── Wipe existing store and WinCred ──────────────────────────────────────
    data_dir = Path(os.getenv("HAUL_DATA_DIR", str(Path.home() / ".haul")))
    for fname in ["credentials.enc", "credentials.key"]:
        p = data_dir / fname
        if p.exists():
            p.unlink()
            ok(f"Removed {fname}")

    try:
        import win32cred
        win32cred.CredDelete("haul-mcp-passphrase", win32cred.CRED_TYPE_GENERIC)
        ok("Cleared Windows Credential Manager entry")
    except Exception:
        pass  # Nothing to clear

    from src.haul.credentials import _Session
    _Session.reset()

    # ── Create new store ──────────────────────────────────────────────────────
    print()
    print(f"  {B}Step 1: Create new passphrase{R}")
    for attempt in range(3):
        pp = ask_secret("Choose passphrase")
        pp2 = ask_secret("Confirm passphrase")
        if pp == pp2:
            break
        warn("Passphrases don't match, try again")
        if attempt == 2:
            print("  Too many attempts. Run reset again.")
            sys.exit(1)

    from src.haul.credentials import init_store, set_credential, save_passphrase_to_wincred
    import platform
    init_store(pp)
    ok("Credential store created")

    if platform.system() == "Windows":
        save_passphrase_to_wincred(pp)
        ok("Passphrase saved to Windows Credential Manager")

    # ── Re-enter credentials ──────────────────────────────────────────────────
    print()
    print(f"  {B}Step 2: IPTorrents{R}")
    ipt_u = ask("Username")
    ipt_p = ask_secret("Password")
    set_credential("IPTORRENTS_USER", ipt_u)
    set_credential("IPTORRENTS_PASS", ipt_p)
    ok("IPTorrents credentials saved")

    print()
    print(f"  {B}Step 3: Synology{R}")
    syno_h = ask("DSM URL", "http://192.168.1.10:5000")
    syno_u = ask("Username", "neil")
    syno_p = ask_secret("Password")
    set_credential("SYNOLOGY_HOST", syno_h)
    set_credential("SYNOLOGY_USER", syno_u)
    set_credential("SYNOLOGY_PASS", syno_p)

    print()
    print(f"  {B}Step 4: Download folders{R}")
    tv  = ask("TV folder",     "Media/TV")
    mov = ask("Movies folder", "Media/Movies")
    oth = ask("Other folder",  "Media/")
    set_credential("DS_DOWNLOAD_DIR_TV",     tv)
    set_credential("DS_DOWNLOAD_DIR_MOVIES", mov)
    set_credential("DS_DOWNLOAD_DIR_OTHER",  oth)
    ok("Download destinations saved")

    print()
    print(f"{B}{G}✅ Reset complete!{R}")
    print(f"\n  Restart the MCP server — it will auto-unlock from WinCred.\n")
    print(f"  {C}Stop-Process -Name python -ErrorAction SilentlyContinue{R}")
    print(f"  {C}cd F:\\haul-app && uv run python -m src.mcp_server --http{R}\n")


if __name__ == "__main__":
    run_reset()
