"""
Haul MCP Server — exposes torrent hunting as MCP tools.

Tools:
  haul_search          — search and score results, return ranked list
  haul_hunt            — full hunt: search → select → confirm → queue
  haul_confirm         — confirm a pending download after haul_hunt
  haul_list_downloads  — list active Download Station tasks
  haul_setup_check     — verify credentials and connectivity

Run:
  uv run python -m src.mcp_server        # stdio
  uv run python -m src.mcp_server --http # HTTP/SSE on port 8766
"""
from __future__ import annotations
import asyncio
import sys
from typing import Any

from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

mcp = FastMCP(
    name="haul",
    version="0.1.0",
    description=(
        "Torrent hunter for IPTorrents. "
        "Searches, scores by quality (2160p+HDR first, then seeder balance), "
        "and sends directly to Synology Download Station. "
        "All credentials PQC-encrypted locally."
    ),
)


@mcp.tool
def haul_search(query: str, min_seeders: int = 5) -> dict[str, Any]:
    """
    Search IPTorrents and return ranked results.
    Shows top 10 candidates with quality scores.
    Best 2160p+HDR is highlighted as recommended.

    query: movie or show title (e.g. 'The Boys S05E01', 'Dune Part Two')
    min_seeders: minimum seeders to consider a torrent viable
    """
    from src.haul.agent import hunt
    result = asyncio.run(hunt(
        query=query,
        min_seeders=min_seeders,
        auto_confirm=False,  # always return without downloading
        dry_run=True,
    ))
    return result


@mcp.tool
def haul_hunt(
    query: str,
    media_type: str = "auto",
    auto_confirm: bool = False,
    min_seeders: int = 5,
    prefer_4k_hdr: bool = True,
) -> dict[str, Any]:
    """
    Hunt for the best torrent and optionally queue it for download.

    query:         movie or show name (e.g. 'The Boys S05E01', 'Severance S02E01 2160p')
    media_type:    'movie', 'tv', or 'auto' (auto-detected from title)
    auto_confirm:  if False (default), returns selection for user to confirm first
    min_seeders:   minimum seeders for a torrent to be considered (default 5)
    prefer_4k_hdr: always prefer 2160p+HDR over 1080p if available (default True)

    Returns either:
      - status='awaiting_confirmation' with selected torrent + all_results
      - status='queued' if auto_confirm=True and download was sent to DS
      - status='dry_run' for preview without downloading
    """
    from src.haul.agent import hunt
    return asyncio.run(hunt(
        query=query,
        media_type=media_type,
        auto_confirm=auto_confirm,
        min_seeders=min_seeders,
        prefer_4k_hdr=prefer_4k_hdr,
    ))


@mcp.tool
def haul_confirm(torrent_id: str, torrent_name: str,
                 media_type: str = "auto") -> dict[str, Any]:
    """
    Confirm and queue a specific torrent after haul_hunt returns 'awaiting_confirmation'.

    torrent_id:   from the selected torrent in haul_hunt response
    torrent_name: from the selected torrent name (used for folder routing)
    media_type:   'movie', 'tv', or 'auto'
    """
    from src.haul.agent import confirm_and_download
    return asyncio.run(confirm_and_download(torrent_id, torrent_name, media_type))


@mcp.tool
def haul_list_downloads() -> list[dict[str, Any]]:
    """
    List all active Synology Download Station tasks with status and progress.
    """
    from src.haul.synology import DownloadStation
    try:
        with DownloadStation() as ds:
            return ds.list_tasks()
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool
def haul_list_folders() -> list[dict[str, Any]]:
    """
    List available shared folders on the Synology NAS.
    Use this to discover valid destination paths before configuring haul.
    Shows folder name, path, and write permission status.
    """
    from src.haul.synology import DownloadStation
    try:
        with DownloadStation() as ds:
            return ds.list_shared_folders()
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool
def haul_setup_check() -> dict[str, Any]:
    """
    Check haul configuration: IPTorrents session and Synology DS connectivity.
    """
    from src.haul.credentials import get_credential
    checks: dict[str, Any] = {}

    # Credentials present?
    checks["iptorrents_user"] = bool(get_credential("IPTORRENTS_USER"))
    checks["iptorrents_pass"] = bool(get_credential("IPTORRENTS_PASS"))
    checks["synology_host"]   = get_credential("SYNOLOGY_HOST", "not set")
    checks["synology_user"]   = bool(get_credential("SYNOLOGY_USER"))
    checks["synology_pass"]   = bool(get_credential("SYNOLOGY_PASS"))
    checks["ds_dir_tv"]       = get_credential("DS_DOWNLOAD_DIR_TV", "/volume1/downloads/tv")
    checks["ds_dir_movies"]   = get_credential("DS_DOWNLOAD_DIR_MOVIES", "/volume1/downloads/movies")

    # Synology connectivity
    host = get_credential("SYNOLOGY_HOST")
    if host:
        try:
            from src.haul.synology import DownloadStation
            with DownloadStation() as ds:
                info = ds.get_info()
                checks["synology_connected"] = info.get("success", False)
        except Exception as e:
            checks["synology_connected"] = False
            checks["synology_error"] = str(e)

    return checks


if __name__ == "__main__":
    if "--http" in sys.argv:
        mcp.run(transport="sse", host="0.0.0.0", port=8766)
    else:
        mcp.run(transport="stdio")
