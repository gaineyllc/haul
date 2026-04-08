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


# ── Priority & Speed ──────────────────────────────────────────────────────────

@mcp.tool
def haul_set_priority(task_id: str, priority: str = "normal") -> dict[str, Any]:
    """
    Set download task priority.
    priority: 'auto' | 'low' | 'normal' | 'high'
    """
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.set_task_priority(task_id, priority)


@mcp.tool
def haul_set_speed_limit(max_download_kb: int = 0,
                         max_upload_kb: int = 0) -> dict[str, Any]:
    """
    Set global Download Station speed limits in KB/s.
    0 = unlimited. Example: max_download_kb=10240 caps at 10 MB/s.
    """
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.set_speed_limit(max_download_kb, max_upload_kb)


@mcp.tool
def haul_get_stats() -> dict[str, Any]:
    """
    Get global Download Station transfer statistics.
    Returns current download/upload speeds and error counts.
    """
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.get_statistics()


# ── File selection ─────────────────────────────────────────────────────────────

@mcp.tool
def haul_list_torrent_files(task_id: str) -> list[dict[str, Any]]:
    """
    List files inside a multi-file torrent.
    Returns each file with index, filename, size, wanted status, and priority.
    Use haul_select_files to choose which files to download.
    """
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.list_torrent_files(task_id)


@mcp.tool
def haul_select_files(task_id: str,
                      wanted_indices: list[int]) -> dict[str, Any]:
    """
    Choose which files to download from a multi-file torrent.
    wanted_indices: list of 0-based file indices from haul_list_torrent_files.
    Example: [0, 2, 3] downloads only files at index 0, 2, and 3.
    """
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.select_torrent_files(task_id, wanted_indices)


# ── Schedule ───────────────────────────────────────────────────────────────────

@mcp.tool
def haul_get_schedule() -> dict[str, Any]:
    """
    Get the current Download Station download schedule.
    Returns whether scheduling is enabled and the 7x24 hour matrix.
    """
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.get_schedule()


@mcp.tool
def haul_set_schedule_hours(start_hour: int, end_hour: int,
                            days: list[int] | None = None) -> dict[str, Any]:
    """
    Set Download Station to only download between certain hours.
    start_hour / end_hour: 0-23 (24h format). Wraps midnight automatically.
    days: list of day indices 0-6 (0=Sunday). None = all days.

    Examples:
      haul_set_schedule_hours(22, 8)         # 10pm to 8am every day
      haul_set_schedule_hours(0, 24)         # always (disable schedule)
      haul_set_schedule_hours(1, 6, [1,2,3,4,5])  # 1-6am weekdays only
    """
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.set_schedule_hours(start_hour, end_hour, days)


@mcp.tool
def haul_disable_schedule() -> dict[str, Any]:
    """
    Disable the download schedule — Download Station runs 24/7.
    """
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.set_schedule(enabled=False)


# ── RSS Feeds ──────────────────────────────────────────────────────────────────

@mcp.tool
def haul_list_rss_sites() -> list[dict[str, Any]]:
    """List all configured RSS feed sites in Download Station."""
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.list_rss_sites()


@mcp.tool
def haul_add_rss_site(url: str) -> dict[str, Any]:
    """
    Add an RSS feed URL to Download Station.
    url: RSS feed URL (e.g. show RSS from a tracker)
    """
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.add_rss_site(url)


@mcp.tool
def haul_delete_rss_site(site_id: str) -> dict[str, Any]:
    """Remove an RSS feed site from Download Station."""
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.delete_rss_site(site_id)


@mcp.tool
def haul_refresh_rss_site(site_id: str) -> dict[str, Any]:
    """Force-refresh an RSS feed now."""
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.refresh_rss_site(site_id)


@mcp.tool
def haul_list_rss_feeds(site_id: str) -> list[dict[str, Any]]:
    """List feed items from an RSS site."""
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.list_rss_feeds(site_id)


# ── RSS Filters (auto-download rules) ──────────────────────────────────────────

@mcp.tool
def haul_list_rss_filters() -> list[dict[str, Any]]:
    """
    List all RSS auto-download filters.
    Filters watch RSS feeds and automatically download matching items.
    """
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.list_rss_filters()


@mcp.tool
def haul_add_rss_filter(
    name: str,
    feed_id: str,
    destination: str,
    match_pattern: str = "",
    exclude_pattern: str = "",
    use_regex: bool = False,
) -> dict[str, Any]:
    """
    Create an RSS auto-download filter — fully automated downloading.

    name:            Filter name (e.g. 'Severance 4K')
    feed_id:         RSS site ID from haul_list_rss_sites
    destination:     Download folder (e.g. 'downloads/tv')
    match_pattern:   Keywords to match in torrent name
    exclude_pattern: Keywords to exclude (e.g. 'CAM TELESYNC')
    use_regex:       Treat patterns as regular expressions

    Example — auto-download 2160p Severance:
      haul_add_rss_filter(
        name='Severance 4K',
        feed_id='site123',
        destination='downloads/tv',
        match_pattern='Severance.*2160p',
        exclude_pattern='CAM|TELESYNC',
        use_regex=True
      )
    """
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.add_rss_filter(
            name, feed_id, destination,
            match_pattern, exclude_pattern, use_regex
        )


@mcp.tool
def haul_delete_rss_filter(filter_id: str) -> dict[str, Any]:
    """Delete an RSS auto-download filter."""
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.delete_rss_filter(filter_id)


# ── BT Search ──────────────────────────────────────────────────────────────────

@mcp.tool
def haul_bt_search(keyword: str) -> dict[str, Any]:
    """
    Search for torrents across all enabled BT search modules in Download Station.
    Returns a task_id — poll with haul_bt_search_results until finished=True.

    Note: This uses Download Station's built-in search (different from IPTorrents).
    Results can be sent directly to DS via haul_bt_add_result.
    """
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.bt_search_start(keyword)


@mcp.tool
def haul_bt_search_results(
    task_id: str,
    offset: int = 0,
    limit: int = 50,
    sort_by: str = "seeds",
) -> dict[str, Any]:
    """
    Get results from a running BT search.
    task_id: from haul_bt_search
    sort_by: 'seeds' | 'name' | 'size' | 'date' | 'peers' | 'download'
    Returns status, finished flag, total count, and list of results.
    """
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.bt_search_results(task_id, offset, limit, sort_by)


@mcp.tool
def haul_bt_search_modules() -> list[dict[str, Any]]:
    """List available BT search modules/trackers configured in Download Station."""
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.bt_search_modules()


@mcp.tool
def haul_bt_add_result(download_uri: str, destination: str) -> dict[str, Any]:
    """
    Add a result from haul_bt_search_results directly to Download Station.
    download_uri: from the bt_search result's download_uri field
    destination:  folder to download to (e.g. 'downloads/movies')
    """
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.add_url(download_uri, destination)


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
