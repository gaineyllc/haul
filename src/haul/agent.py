"""
Haul agent — orchestrates search → select → confirm → download.
"""
from __future__ import annotations
import asyncio
from typing import Any

from src.haul.browser import IPTSession
from src.haul.quality import select_best, explain_selection, TorrentResult
from src.haul.synology import DownloadStation
from src.haul.credentials import get_credential, unlock_store


async def hunt(
    query: str,
    media_type: str = "auto",
    auto_confirm: bool = False,
    min_seeders: int = 5,
    prefer_4k_hdr: bool = True,
    dry_run: bool = False,
    on_status: Any = None,
) -> dict[str, Any]:
    """
    Main haul agent entrypoint.

    1. Search IPTorrents for query
    2. Score and select best torrent (2160p+HDR first, then balance quality/availability)
    3. Present selection to user for confirmation (unless auto_confirm)
    4. Download .torrent bytes
    5. Send to Synology Download Station
    6. Return result dict
    """

    def status(msg: str) -> None:
        if on_status: on_status(msg)

    # ── Auth ───────────────────────────────────────────────────────────────────
    username = get_credential("IPTORRENTS_USER", "")
    password = get_credential("IPTORRENTS_PASS", "")

    if not username or not password:
        return {"error": "IPTorrents credentials not configured. Run: haul setup"}

    # ── Search ─────────────────────────────────────────────────────────────────
    status(f"Searching IPTorrents for: {query}")

    async with IPTSession(headless=True) as session:
        await session.ensure_logged_in(username, password)
        results = await session.search(query, max_pages=2)

        if not results:
            return {"error": f"No results found for: {query}"}

        status(f"Found {len(results)} results")

        # ── Select ─────────────────────────────────────────────────────────────
        chosen = select_best(results, min_seeders=min_seeders,
                             prefer_4k_hdr=prefer_4k_hdr)
        explanation = explain_selection(results, chosen)

        if not chosen:
            return {"error": "No viable torrents found (all below min_seeders or cam)"}

        status(f"Selected: {chosen.name}")

        # ── Confirmation ───────────────────────────────────────────────────────
        if not auto_confirm and not dry_run:
            return {
                "status": "awaiting_confirmation",
                "selected": _torrent_dict(chosen),
                "explanation": explanation,
                "all_results": [_torrent_dict(r) for r in
                                sorted(results, key=lambda x: -x.quality_score)[:10]],
            }

        if dry_run:
            return {
                "status": "dry_run",
                "selected": _torrent_dict(chosen),
                "explanation": explanation,
                "would_download_to": DownloadStation.destination_for(
                    chosen.name, media_type
                ),
            }

        # ── Download .torrent ──────────────────────────────────────────────────
        status("Downloading .torrent file...")
        torrent_bytes = await session.download_torrent(chosen.torrent_id)

        # ── Send to Download Station ───────────────────────────────────────────
        destination = DownloadStation.destination_for(chosen.name, media_type)
        status(f"Adding to Download Station → {destination}")

        with DownloadStation() as ds:
            result = ds.add_torrent_file(
                torrent_bytes,
                destination=destination,
                filename=f"{chosen.torrent_id}.torrent",
            )

        if result.get("success"):
            return {
                "status": "queued",
                "selected": _torrent_dict(chosen),
                "destination": destination,
                "explanation": explanation,
            }
        else:
            return {
                "status": "ds_error",
                "error": str(result),
                "selected": _torrent_dict(chosen),
            }


async def confirm_and_download(
    torrent_id: str,
    torrent_name: str,
    media_type: str = "auto",
) -> dict[str, Any]:
    """
    Download and queue a specific torrent ID after user confirmation.
    Called after hunt() returns 'awaiting_confirmation'.
    """
    username = get_credential("IPTORRENTS_USER", "")
    password = get_credential("IPTORRENTS_PASS", "")

    async with IPTSession(headless=True) as session:
        await session.ensure_logged_in(username, password)
        torrent_bytes = await session.download_torrent(torrent_id)

    destination = DownloadStation.destination_for(torrent_name, media_type)
    with DownloadStation() as ds:
        result = ds.add_torrent_file(
            torrent_bytes,
            destination=destination,
            filename=f"{torrent_id}.torrent",
        )

    return {
        "status": "queued" if result.get("success") else "error",
        "destination": destination,
        "torrent_id": torrent_id,
        "ds_response": result,
    }


def _torrent_dict(r: TorrentResult) -> dict:
    return {
        "id":           r.torrent_id,
        "name":         r.name,
        "download_url": r.download_url,
        "resolution":   r.resolution,
        "hdr_type":     r.hdr_type,
        "source":       r.source,
        "audio":        r.audio,
        "size":         r.size_str,
        "seeders":      r.seeders,
        "leechers":     r.leechers,
        "completed":    r.completed,
        "quality_score": r.quality_score,
        "freeleech":    r.freeleech,
    }
