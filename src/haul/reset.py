"""
haul credential reset — clears all keychain entries and re-enters them.

Usage:
  uv run python -m src.haul.reset
"""
from __future__ import annotations
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

R="\033[0m"; B="\033[1m"; G="\033[32m"; Y="\033[33m"; C="\033[36m"
def ok(m):   print(f"  {G}✅{R} {m}")
def warn(m): print(f"  {Y}⚠️ {R} {m}")
def ask(p, d=""): v=input(f"  {B}{p}{f' [{d}]' if d else ''}: {R}").strip(); return v or d
def ask_secret(p): return getpass.getpass(f"  {B}{p}: {R}")


def run_reset(silent: bool = False) -> None:
    if not silent:
        print(f"\n{B}{C}╔══════════════════════════════╗")
        print(f"║  🔑 haul credential reset    ║")
        print(f"╚══════════════════════════════╝{R}\n")
        confirm = input(f"  {B}Reset all credentials? [Y/n]: {R}").strip().lower()
        if confirm not in ("", "y", "yes"):
            print("  Cancelled.")
            return

    from src.haul.credentials import set_credential, delete_credential, list_credentials
    import keyring

    # Clear existing
    for key in list_credentials():
        try:
            keyring.delete_password("haul", key)
        except Exception:
            pass
    from src.haul.credentials import _index_path
    p = _index_path()
    if p.exists():
        p.unlink()
    ok("Cleared existing credentials")

    print()
    print(f"  {B}IPTorrents{R}")
    set_credential("IPTORRENTS_USER", ask("Username"))
    set_credential("IPTORRENTS_PASS", ask_secret("Password"))
    ok("IPTorrents saved")

    print()
    print(f"  {B}Synology{R}")
    set_credential("SYNOLOGY_HOST", ask("DSM URL", "http://192.168.1.10:5000"))
    set_credential("SYNOLOGY_USER", ask("Username", "neil"))
    set_credential("SYNOLOGY_PASS", ask_secret("Password"))
    set_credential("DS_DOWNLOAD_DIR_TV",     ask("TV folder",     "Media/TV"))
    set_credential("DS_DOWNLOAD_DIR_MOVIES", ask("Movies folder", "Media/Movies"))
    set_credential("DS_DOWNLOAD_DIR_OTHER",  ask("Other folder",  "Media/"))
    ok("Synology saved")

    print(f"\n{B}{G}✅ Reset complete — haul is ready.{R}\n")
    print(f"  Restart the MCP server:")
    print(f"  {C}Stop-Process -Name python -ErrorAction SilentlyContinue{R}")
    print(f"  {C}uv run python -m src.mcp_server --http{R}\n")


if __name__ == "__main__":
    run_reset()
