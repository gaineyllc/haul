"""Tests for the agent primitive separation."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.haul.quality import TorrentResult


def _make_result(name, seeders=100, torrent_id="123"):
    return TorrentResult(
        name=name, torrent_id=torrent_id, download_url=f"/dl/{torrent_id}",
        seeders=seeders, leechers=10, completed=500
    )


# ── hunt() confirm gate ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hunt_returns_awaiting_confirmation_by_default():
    """hunt() without auto_confirm must NOT download anything."""
    from src.haul.agent import hunt

    mock_results = [_make_result("Movie 2160p HDR WEB-DL", seeders=100)]

    with patch("src.haul.agent.search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = {
            "status": "ok",
            "query": "Movie",
            "total": 1,
            "recommended": {
                "id": "999", "name": "Movie 2160p HDR WEB-DL",
                "resolution": "2160p", "hdr_type": "HDR",
                "seeders": 100, "quality_score": 1200.0,
                "source": "WEB-DL", "audio": "", "size": "6 GB",
                "leechers": 5, "completed": 200, "freeleech": False, "is_cam": False,
                "download_url": "/dl/999",
            },
            "results": [],
            "explanation": "Selected: Movie 2160p HDR WEB-DL",
        }

        result = await hunt(query="Movie", auto_confirm=False)

    assert result["status"] == "awaiting_confirmation"
    assert "next_step" in result
    assert "haul_download" in result["next_step"]


@pytest.mark.asyncio
async def test_hunt_dry_run_never_downloads():
    """dry_run=True must never call download()."""
    from src.haul.agent import hunt

    with patch("src.haul.agent.search", new_callable=AsyncMock) as mock_search, \
         patch("src.haul.agent.download", new_callable=AsyncMock) as mock_dl:

        mock_search.return_value = {
            "status": "ok", "query": "Movie", "total": 1,
            "recommended": {
                "id": "999", "name": "Movie 2160p HDR",
                "resolution": "2160p", "hdr_type": "HDR",
                "seeders": 100, "quality_score": 1200.0,
                "source": "WEB-DL", "audio": "", "size": "6 GB",
                "leechers": 5, "completed": 200, "freeleech": False, "is_cam": False,
                "download_url": "/dl/999",
            },
            "results": [],
            "explanation": "",
        }

        result = await hunt(query="Movie", dry_run=True)

    assert result["status"] == "dry_run"
    mock_dl.assert_not_called()


@pytest.mark.asyncio
async def test_hunt_auto_confirm_calls_download():
    """auto_confirm=True should call download() with the recommended torrent."""
    from src.haul.agent import hunt

    with patch("src.haul.agent.search", new_callable=AsyncMock) as mock_search, \
         patch("src.haul.agent.download", new_callable=AsyncMock) as mock_dl:

        mock_search.return_value = {
            "status": "ok", "query": "Movie", "total": 1,
            "recommended": {
                "id": "999", "name": "Movie 2160p HDR WEB-DL S01E01",
                "resolution": "2160p", "hdr_type": "HDR",
                "seeders": 100, "quality_score": 1200.0,
                "source": "WEB-DL", "audio": "Atmos", "size": "6 GB",
                "leechers": 5, "completed": 200, "freeleech": False, "is_cam": False,
                "download_url": "/dl/999",
            },
            "results": [],
            "explanation": "",
        }
        mock_dl.return_value = {"status": "queued", "destination": "downloads/tv"}

        result = await hunt(query="Movie S01E01", auto_confirm=True)

    mock_dl.assert_called_once()
    call_kwargs = mock_dl.call_args
    assert call_kwargs.kwargs["torrent_id"] == "999"


@pytest.mark.asyncio
async def test_hunt_no_results():
    """hunt() with no results returns no_results status."""
    from src.haul.agent import hunt

    with patch("src.haul.agent.search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = {
            "status": "no_results", "query": "xyzzy12345",
            "results": [], "recommended": None,
        }
        result = await hunt(query="xyzzy12345")

    assert result["status"] == "no_results"


# ── search / download independence ───────────────────────────────────────────

def test_search_and_download_are_separate_imports():
    """search and download should be importable and callable independently."""
    from src.haul.agent import search, download, hunt
    assert callable(search)
    assert callable(download)
    assert callable(hunt)
