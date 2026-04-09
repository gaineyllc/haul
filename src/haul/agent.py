"""
Haul agent — clean separation of search and download concerns.

Primitives:
  search()   — find and score torrents, no side effects
  download() — fetch .torrent + create DS task, no searching

Convenience:
  hunt()     — search → pick best → confirm gate → download
  confirm_and_download() — download a specific torrent by ID
"""
from __future__ import annotations
import asyncio
from typing import Any

from src.haul.browser import IPTSession
from src.haul.quality import select_best, explain_selection, TorrentResult
from src.haul.synology import DownloadStation
from src.haul.credentials import get_credential


# ── Primitive: Search ─────────────────────────────────────────────────────────

async def search(
    query: str,
    min_seeders: int = 5,
    prefer_4k_hdr: bool = True,
    max_pages: int = 2,
) -> dict[str, Any]:
    """
    Search IPTorrents and return ranked results. No side effects.
    Automatically normalizes natural language queries.

    Returns:
      status:         'ok' | 'no_results' | 'error'
      results:        list of all candidates (sorted by quality_score desc)
      recommended:    the best pick according to scoring logic
      explanation:    human-readable explanation of the recommendation
      query:          the original query
      normalized_query: what was actually searched
    """
    from src.haul.query import normalize

    username = get_credential("IPTORRENTS_USER", "")
    password = get_credential("IPTORRENTS_PASS", "")

    if not username or not password:
        return {
            "status": "error",
            "error": "IPTorrents credentials not configured. Run: python -m src.haul.setup",
        }

    # Normalize natural language → clean search string
    parsed = normalize(query)
    search_str = parsed.search_string

    # Inherit prefer_4k_hdr from quality hint if user asked for 4K
    if parsed.quality_hint == "2160p":
        prefer_4k_hdr = True

    async with IPTSession(headless=True) as session:
        await session.ensure_logged_in(username, password)
        raw_results = await session.search(search_str, max_pages=max_pages)

    if not raw_results:
        return {"status": "no_results", "query": query,
                "normalized_query": search_str, "results": [], "recommended": None}

    # Score, sort, select with tier fallback
    sorted_results = sorted(raw_results, key=lambda r: -r.quality_score)
    recommended, tier = select_best(raw_results, min_seeders=min_seeders,
                                    prefer_4k_hdr=prefer_4k_hdr)
    explanation = explain_selection(raw_results, recommended, tier)

    return {
        "status":           "ok",
        "query":            query,
        "normalized_query": search_str,
        "quality_tier":     tier,  # e.g. '2160p DV+HDR', '1080p WEB-DL'
        "parsed": {
            "title":       parsed.title,
            "season":      parsed.season,
            "episode":     parsed.episode,
            "season_pack": parsed.season_pack,
            "quality_hint":parsed.quality_hint,
            "media_type":  parsed.media_type,
        },
        "total":       len(sorted_results),
        "recommended": _torrent_dict(recommended) if recommended else None,
        "results":     [_torrent_dict(r) for r in sorted_results],
        "explanation": explanation,
    }


# ── Primitive: Download ───────────────────────────────────────────────────────

async def download(
    torrent_id: str,
    torrent_name: str,
    destination: str | None = None,
    media_type: str = "auto",
) -> dict[str, Any]:
    """
    Download a specific torrent and create a Download Station task.
    No searching involved.

    Args:
        torrent_id:    IPTorrents torrent ID (from search results)
        torrent_name:  Torrent name (used for smart folder routing if no destination)
        destination:   Explicit DS destination path. If None, auto-routes by media_type/name.
        media_type:    'movie' | 'tv' | 'auto'

    Returns:
        status:      'queued' | 'ds_error' | 'error'
        destination: folder the task was sent to
        task:        DS task info if available
    """
    username = get_credential("IPTORRENTS_USER", "")
    password = get_credential("IPTORRENTS_PASS", "")

    if not username or not password:
        return {"status": "error",
                "error": "IPTorrents credentials not configured."}

    # ── Fetch .torrent bytes ───────────────────────────────────────────────────
    try:
        async with IPTSession(headless=True) as session:
            await session.ensure_logged_in(username, password)
            torrent_bytes = await session.download_torrent(torrent_id)
    except Exception as e:
        return {"status": "error", "error": f"Failed to fetch torrent: {e}"}

    # ── Resolve destination ────────────────────────────────────────────────────
    if not destination:
        destination = DownloadStation.destination_for(torrent_name, media_type)

    # ── Create DS task ─────────────────────────────────────────────────────────
    try:
        with DownloadStation() as ds:
            result = ds.add_torrent_file(
                torrent_bytes,
                destination=destination,
                filename=f"{torrent_id}.torrent",
            )
        if result.get("success"):
            return {
                "status":      "queued",
                "torrent_id":  torrent_id,
                "torrent_name": torrent_name,
                "destination": destination,
            }
        else:
            return {
                "status": "ds_error",
                "error":  str(result),
                "torrent_id": torrent_id,
            }
    except Exception as e:
        return {"status": "error", "error": f"Download Station error: {e}"}


# ── Convenience: Hunt (search + confirm gate + download) ──────────────────────

async def hunt(
    query: str,
    media_type: str = "auto",
    auto_confirm: bool = False,
    min_seeders: int = 5,
    prefer_4k_hdr: bool = True,
    destination: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Full pipeline: search → pick best → confirm gate → download.
    Composed from the search() and download() primitives.

    Returns:
      If auto_confirm=False (default):
        status='awaiting_confirmation' with recommended + all results
        → Call download() directly with the torrent_id to proceed

      If auto_confirm=True:
        status='queued' or error

      If dry_run=True:
        status='dry_run' — shows what would be downloaded without doing it
    """
    # Step 1: Search (normalizes query internally)
    search_result = await search(
        query=query,
        min_seeders=min_seeders,
        prefer_4k_hdr=prefer_4k_hdr,
    )

    if search_result["status"] != "ok":
        return search_result

    recommended = search_result.get("recommended")
    if not recommended:
        return {"status": "no_viable_torrents",
                "error": "All results below min_seeders threshold or cam-only"}

    tier = search_result.get("quality_tier", "")

    # Use parsed media_type if caller didn't specify
    parsed_media_type = search_result.get("parsed", {}).get("media_type", "auto")
    effective_media_type = media_type if media_type != "auto" else parsed_media_type
    dest = destination or DownloadStation.destination_for(
        recommended["name"], effective_media_type
    )

    # Step 2: Dry run
    if dry_run:
        return {
            "status":            "dry_run",
            "query":             query,
            "normalized_query":  search_result.get("normalized_query", query),
            "quality_tier":      tier,
            "recommended":       recommended,
            "would_download_to": dest,
            "explanation":       search_result["explanation"],
            "all_results":       search_result["results"][:10],
        }

    # Step 3: Confirm gate
    if not auto_confirm:
        return {
            "status":           "awaiting_confirmation",
            "query":            query,
            "normalized_query": search_result.get("normalized_query", query),
            "quality_tier":     tier,
            "recommended":      recommended,
            "destination":      dest,
            "explanation":      search_result["explanation"],
            "all_results":      search_result["results"][:10],
            "next_step": (
                f"Call haul_download("
                f"torrent_id='{recommended['id']}', "
                f"torrent_name='{recommended['name'][:50]}', "
                f"destination='{dest}') to proceed."
            ),
        }

    # Step 4: Download
    return await download(
        torrent_id=recommended["id"],
        torrent_name=recommended["name"],
        destination=dest,
        media_type=effective_media_type,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _torrent_dict(r: TorrentResult | None) -> dict | None:
    if r is None:
        return None
    return {
        "id":            r.torrent_id,
        "name":          r.name,
        "download_url":  r.download_url,
        "resolution":    r.resolution,
        "hdr_type":      r.hdr_type,
        "source":        r.source,
        "audio":         r.audio,
        "size":          r.size_str,
        "seeders":       r.seeders,
        "leechers":      r.leechers,
        "completed":     r.completed,
        "quality_score": r.quality_score,
        "freeleech":     r.freeleech,
        "is_cam":        r.is_cam,
    }
