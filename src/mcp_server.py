"""
Haul MCP Server
───────────────
Clean separation of search and download concerns.

PRIMITIVES (do one thing):
  haul_search    — find + score torrents, zero side effects
  haul_download  — fetch .torrent + create DS task, no searching

CONVENIENCE (composed from primitives):
  haul_hunt      — search → confirm gate → download in one call

DOWNLOAD STATION MANAGEMENT:
  haul_list_downloads, haul_pause_task, haul_resume_task, haul_delete_task
  haul_set_priority, haul_set_speed_limit, haul_get_stats
  haul_list_torrent_files, haul_select_files
  haul_get_schedule, haul_set_schedule_hours, haul_disable_schedule
  haul_list_rss_sites, haul_add_rss_site, haul_delete_rss_site
  haul_refresh_rss_site, haul_list_rss_feeds
  haul_list_rss_filters, haul_add_rss_filter, haul_delete_rss_filter
  haul_bt_search, haul_bt_search_results, haul_bt_search_modules
  haul_bt_add_result, haul_list_folders, haul_setup_check

Run:
  uv run python -m src.mcp_server        # stdio
  uv run python -m src.mcp_server --http # HTTP/SSE on :8766
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
    version="0.2.0",
    description=(
        "Torrent hunter for IPTorrents → Synology Download Station. "
        "haul_search finds and scores torrents (2160p+HDR first). "
        "haul_download creates the DS task. "
        "haul_hunt combines both with a confirmation gate. "
        "Full Download Station management included."
    ),
)


# ── PRIMITIVE: Search ─────────────────────────────────────────────────────────

@mcp.tool
def haul_search(
    query: str,
    min_seeders: int = 5,
    prefer_4k_hdr: bool = True,
) -> dict[str, Any]:
    """
    Search IPTorrents and return scored results. No side effects — safe to call anytime.

    Returns:
      - recommended: the best pick (2160p+HDR first, then seeder-balanced)
      - results:     all candidates ranked by quality score
      - explanation: why the recommendation was chosen

    After reviewing, call haul_download() with the chosen torrent_id.

    query:        movie or show name (e.g. 'The Boys S05E01', 'Dune Part Two')
    min_seeders:  minimum seeders for a torrent to be considered viable
    prefer_4k_hdr: always prefer 2160p+HDR when available
    """
    from src.haul.agent import search
    return asyncio.run(search(
        query=query,
        min_seeders=min_seeders,
        prefer_4k_hdr=prefer_4k_hdr,
    ))


# ── PRIMITIVE: Download ───────────────────────────────────────────────────────

@mcp.tool
def haul_download(
    torrent_id: str,
    torrent_name: str,
    destination: str | None = None,
    media_type: str = "auto",
) -> dict[str, Any]:
    """
    Download a specific torrent and create a Synology Download Station task.
    No searching — use haul_search first to get a torrent_id.

    torrent_id:   from haul_search results (the 'id' field)
    torrent_name: from haul_search results (the 'name' field) — used for folder routing
    destination:  explicit DS folder path (e.g. 'downloads/movies').
                  If omitted, auto-routes: S01E01 patterns → TV, otherwise → Movies.
    media_type:   'movie' | 'tv' | 'auto' — overrides auto-detection

    Returns status='queued' on success with the destination folder used.
    """
    from src.haul.agent import download
    return asyncio.run(download(
        torrent_id=torrent_id,
        torrent_name=torrent_name,
        destination=destination,
        media_type=media_type,
    ))


# ── CONVENIENCE: Hunt (search + confirm gate + download) ──────────────────────

@mcp.tool
def haul_hunt(
    query: str,
    media_type: str = "auto",
    auto_confirm: bool = False,
    min_seeders: int = 5,
    prefer_4k_hdr: bool = True,
    destination: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Full pipeline: search → score → confirm gate → download.
    Convenience wrapper composed from haul_search + haul_download.

    Default behaviour (auto_confirm=False):
      Returns status='awaiting_confirmation' with the recommended torrent
      and a next_step hint showing exactly which haul_download call to make.
      → Review the recommendation, then call haul_download() to proceed.

    auto_confirm=True:
      Skips confirmation and downloads immediately.
      Use only when you're confident in the query and quality settings.

    dry_run=True:
      Shows what would be selected and where it would go — no download.

    query:        title to search for
    media_type:   'movie' | 'tv' | 'auto'
    destination:  explicit DS folder (overrides auto-routing)
    min_seeders:  minimum seeders threshold
    prefer_4k_hdr: prefer 2160p+HDR results over 1080p
    """
    from src.haul.agent import hunt
    return asyncio.run(hunt(
        query=query,
        media_type=media_type,
        auto_confirm=auto_confirm,
        min_seeders=min_seeders,
        prefer_4k_hdr=prefer_4k_hdr,
        destination=destination,
        dry_run=dry_run,
    ))


# ── Download Station: Task management ─────────────────────────────────────────

@mcp.tool
def haul_list_downloads() -> list[dict[str, Any]]:
    """List all active Download Station tasks with status, progress %, and speed."""
    from src.haul.synology import DownloadStation
    try:
        with DownloadStation() as ds:
            return ds.list_tasks()
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool
def haul_get_task(task_id: str) -> dict[str, Any]:
    """Get detailed info for a specific Download Station task."""
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.get_task(task_id)


@mcp.tool
def haul_pause_task(task_id: str) -> dict[str, Any]:
    """Pause a Download Station task."""
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.pause_task(task_id)


@mcp.tool
def haul_resume_task(task_id: str) -> dict[str, Any]:
    """Resume a paused Download Station task."""
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.resume_task(task_id)


@mcp.tool
def haul_delete_task(task_id: str, force_complete: bool = False) -> dict[str, Any]:
    """
    Delete a Download Station task.
    force_complete=True also deletes already-downloaded files.
    """
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.delete_task(task_id, force_complete)


@mcp.tool
def haul_edit_destination(task_id: str, destination: str) -> dict[str, Any]:
    """Change the destination folder of a pending (not yet started) task."""
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.edit_destination(task_id, destination)


# ── Download Station: Priority & Speed ────────────────────────────────────────

@mcp.tool
def haul_set_priority(task_id: str, priority: str = "normal") -> dict[str, Any]:
    """
    Set task download priority.
    priority: 'auto' | 'low' | 'normal' | 'high'
    """
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.set_task_priority(task_id, priority)


@mcp.tool
def haul_set_speed_limit(max_download_kb: int = 0,
                         max_upload_kb: int = 0) -> dict[str, Any]:
    """
    Set global speed limits in KB/s. 0 = unlimited.
    Example: max_download_kb=10240 caps downloads at 10 MB/s.
    """
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.set_speed_limit(max_download_kb, max_upload_kb)


@mcp.tool
def haul_get_stats() -> dict[str, Any]:
    """Get current global download/upload speeds and error counts."""
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.get_statistics()


# ── Download Station: File selection ──────────────────────────────────────────

@mcp.tool
def haul_list_torrent_files(task_id: str) -> list[dict[str, Any]]:
    """
    List files inside a multi-file torrent with index, size, wanted status.
    Use haul_select_files to choose which to download.
    """
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.list_torrent_files(task_id)


@mcp.tool
def haul_select_files(task_id: str, wanted_indices: list[int]) -> dict[str, Any]:
    """
    Choose which files to download from a multi-file torrent.
    wanted_indices: 0-based file indices from haul_list_torrent_files.
    """
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.select_torrent_files(task_id, wanted_indices)


# ── Download Station: Schedule ────────────────────────────────────────────────

@mcp.tool
def haul_get_schedule() -> dict[str, Any]:
    """Get the current download schedule (enabled flag + 7x24 hour matrix)."""
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.get_schedule()


@mcp.tool
def haul_set_schedule_hours(start_hour: int, end_hour: int,
                            days: list[int] | None = None) -> dict[str, Any]:
    """
    Only download between start_hour and end_hour (24h format, wraps midnight).
    days: 0-6 (0=Sunday). None = all days.
    Example: haul_set_schedule_hours(22, 8) = download 10pm–8am every day.
    """
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.set_schedule_hours(start_hour, end_hour, days)


@mcp.tool
def haul_disable_schedule() -> dict[str, Any]:
    """Disable schedule — Download Station runs 24/7."""
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.set_schedule(enabled=False)


# ── Download Station: RSS Feeds ───────────────────────────────────────────────

@mcp.tool
def haul_list_rss_sites() -> list[dict[str, Any]]:
    """List all configured RSS feed sites."""
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.list_rss_sites()


@mcp.tool
def haul_add_rss_site(url: str) -> dict[str, Any]:
    """Add an RSS feed URL to Download Station."""
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.add_rss_site(url)


@mcp.tool
def haul_delete_rss_site(site_id: str) -> dict[str, Any]:
    """Remove an RSS feed site."""
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
    """List items from an RSS feed site."""
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.list_rss_feeds(site_id)


# ── Download Station: RSS Filters ─────────────────────────────────────────────

@mcp.tool
def haul_list_rss_filters() -> list[dict[str, Any]]:
    """List all RSS auto-download filters."""
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
    Create an RSS auto-download filter.
    Watches a feed and auto-downloads matching items — no manual intervention.

    Example — auto-download 2160p Severance:
      haul_add_rss_filter(
        name='Severance 4K', feed_id='site123',
        destination='downloads/tv',
        match_pattern='Severance.*2160p',
        exclude_pattern='CAM|TELESYNC',
        use_regex=True
      )
    """
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.add_rss_filter(name, feed_id, destination,
                                 match_pattern, exclude_pattern, use_regex)


@mcp.tool
def haul_delete_rss_filter(filter_id: str) -> dict[str, Any]:
    """Delete an RSS auto-download filter."""
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.delete_rss_filter(filter_id)


# ── Download Station: BT Search ───────────────────────────────────────────────

@mcp.tool
def haul_bt_search(keyword: str) -> dict[str, Any]:
    """
    Search across all BT search modules configured in Download Station.
    Returns a task_id — poll with haul_bt_search_results until finished=True.
    """
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.bt_search_start(keyword)


@mcp.tool
def haul_bt_search_results(task_id: str, offset: int = 0,
                           limit: int = 50,
                           sort_by: str = "seeds") -> dict[str, Any]:
    """
    Poll results from haul_bt_search.
    sort_by: 'seeds' | 'name' | 'size' | 'date' | 'peers' | 'download'
    """
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.bt_search_results(task_id, offset, limit, sort_by)


@mcp.tool
def haul_bt_search_modules() -> list[dict[str, Any]]:
    """List BT search modules/trackers available in Download Station."""
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.bt_search_modules()


@mcp.tool
def haul_bt_add_result(download_uri: str, destination: str) -> dict[str, Any]:
    """
    Add a BT search result directly to Download Station.
    download_uri: from haul_bt_search_results item's download_uri field.
    destination:  e.g. 'downloads/movies'
    """
    from src.haul.synology import DownloadStation
    with DownloadStation() as ds:
        return ds.add_url(download_uri, destination)


# ── Utilities ─────────────────────────────────────────────────────────────────

@mcp.tool
def haul_list_folders() -> list[dict[str, Any]]:
    """
    List shared folders on the Synology NAS.
    Use to discover valid destination paths before downloading.
    """
    from src.haul.synology import DownloadStation
    try:
        with DownloadStation() as ds:
            return ds.list_shared_folders()
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool
def haul_setup_check() -> dict[str, Any]:
    """Check credentials and connectivity: IPTorrents session + Synology DS."""
    from src.haul.credentials import get_credential
    checks: dict[str, Any] = {
        "iptorrents_user": bool(get_credential("IPTORRENTS_USER")),
        "iptorrents_pass": bool(get_credential("IPTORRENTS_PASS")),
        "synology_host":   get_credential("SYNOLOGY_HOST", "not set"),
        "synology_user":   bool(get_credential("SYNOLOGY_USER")),
        "synology_pass":   bool(get_credential("SYNOLOGY_PASS")),
        "ds_dir_tv":       get_credential("DS_DOWNLOAD_DIR_TV",     "/volume1/downloads/tv"),
        "ds_dir_movies":   get_credential("DS_DOWNLOAD_DIR_MOVIES", "/volume1/downloads/movies"),
    }
    host = get_credential("SYNOLOGY_HOST")
    if host:
        try:
            from src.haul.synology import DownloadStation
            with DownloadStation() as ds:
                info = ds.get_info()
                checks["synology_connected"] = info.get("success", False)
                checks["ds_version"] = info.get("data", {}).get("version", "")
        except Exception as e:
            checks["synology_connected"] = False
            checks["synology_error"] = str(e)
    return checks


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--http" in sys.argv:
        mcp.run(transport="sse", host="0.0.0.0", port=8766)
    else:
        mcp.run(transport="stdio")
