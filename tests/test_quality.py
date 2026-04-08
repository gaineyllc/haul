"""Tests for quality scoring and selection logic."""
import pytest
from src.haul.quality import (
    TorrentResult, score, select_best, explain_selection,
    _resolution, _hdr_type, _source
)


def make(name, seeders=100, leechers=10, completed=500):
    return TorrentResult(
        name=name, torrent_id="123", download_url="/dl/123",
        seeders=seeders, leechers=leechers, completed=completed
    )


# ── Resolution detection ──────────────────────────────────────────────────────

def test_resolution_4k():
    assert _resolution("The Boys S05E01 2160p WEB h265-ETHEL") == "2160p"

def test_resolution_1080():
    assert _resolution("The Boys S05E01 1080p WEB h264-ETHEL") == "1080p"

def test_resolution_720():
    assert _resolution("Show S01E01 720p HDTV x264") == "720p"


# ── HDR detection ─────────────────────────────────────────────────────────────

def test_hdr_dv_and_hdr():
    assert "DV" in _hdr_type("Movie 2160p DV HDR WEB-DL")
    assert "HDR" in _hdr_type("Movie 2160p DV HDR WEB-DL")

def test_hdr_dolby_vision():
    assert "DV" in _hdr_type("Movie 2160p DoVi WEB-DL")

def test_hdr_none():
    assert _hdr_type("Show S01E01 1080p WEB h264") == ""


# ── Source detection ──────────────────────────────────────────────────────────

def test_source_webdl():
    assert _source("Movie 1080p AMZN WEB-DL DDP5.1 H264") == "WEB-DL"

def test_source_remux():
    assert _source("Movie 2160p REMUX") == "REMUX"

def test_source_webrip():
    assert _source("Movie 1080p WEBRip x265") == "WEBRip"


# ── Scoring ───────────────────────────────────────────────────────────────────

def test_4k_beats_1080():
    s4k = score("Movie 2160p WEB-DL", seeders=100)
    s1080 = score("Movie 1080p WEB-DL", seeders=100)
    assert s4k > s1080

def test_hdr_bonus():
    s_hdr = score("Movie 2160p HDR WEB-DL", seeders=100)
    s_sdr = score("Movie 2160p WEB-DL", seeders=100)
    assert s_hdr > s_sdr

def test_dv_beats_hdr():
    s_dv  = score("Movie 2160p DV HDR WEB-DL DDP5.1 Atmos", seeders=100)
    s_hdr = score("Movie 2160p HDR WEB-DL", seeders=100)
    assert s_dv > s_hdr

def test_cam_penalty():
    s_cam  = score("Movie 2160p CAM", seeders=100)
    s_good = score("Movie 1080p WEB-DL", seeders=100)
    assert s_cam < s_good

def test_zero_seeders_scores_zero():
    assert score("Movie 2160p WEB-DL", seeders=0) == 0.0


# ── Selection ─────────────────────────────────────────────────────────────────

def test_select_prefers_4k_hdr():
    results = [
        make("Movie 1080p WEB-DL", seeders=500),
        make("Movie 2160p HDR WEB-DL", seeders=50),
        make("Movie 2160p WEB h265", seeders=200),
    ]
    chosen = select_best(results, min_seeders=5)
    assert chosen is not None
    assert "2160p" in chosen.name
    assert "HDR" in chosen.name

def test_select_falls_back_when_no_4k():
    results = [
        make("Movie 1080p WEB-DL H264 AMZN", seeders=500),
        make("Movie 720p HDTV", seeders=50),
    ]
    chosen = select_best(results, min_seeders=5)
    assert chosen is not None
    assert "1080p" in chosen.name

def test_select_ignores_dead_torrents():
    results = [
        make("Movie 2160p HDR WEB-DL", seeders=0),
        make("Movie 1080p WEB-DL", seeders=100),
    ]
    chosen = select_best(results, min_seeders=5)
    assert chosen is not None
    assert "1080p" in chosen.name

def test_select_ignores_cams():
    results = [
        make("Movie 2160p CAM", seeders=1000),
        make("Movie 1080p WEB-DL", seeders=100),
    ]
    chosen = select_best(results, min_seeders=5)
    assert chosen is not None
    assert "CAM" not in chosen.name

def test_explain_selection():
    results = [make("Movie 2160p HDR WEB-DL", seeders=100)]
    chosen = select_best(results)
    text = explain_selection(results, chosen)
    assert "Selected" in text
