"""Tests for Synology destination normalization and routing."""
from src.haul.synology import _normalize_destination, DownloadStation


def test_strip_volume1():
    assert _normalize_destination("/volume1/downloads/movies") == "downloads/movies"

def test_strip_volume2():
    assert _normalize_destination("/volume2/downloads/tv") == "downloads/tv"

def test_already_normalized():
    assert _normalize_destination("downloads/movies") == "downloads/movies"

def test_strip_leading_slash():
    assert _normalize_destination("/downloads/movies") == "downloads/movies"

def test_windows_backslash():
    assert _normalize_destination("downloads\\movies") == "downloads/movies"

def test_routing_tv_explicit():
    dest = DownloadStation.destination_for("anything", media_type="tv")
    assert "tv" in dest.lower() or "download" in dest.lower()

def test_routing_movie_explicit():
    dest = DownloadStation.destination_for("anything", media_type="movie")
    assert "movie" in dest.lower() or "download" in dest.lower()

def test_routing_tv_auto_s01e01():
    dest = DownloadStation.destination_for("The Boys S05E01 2160p WEB-DL")
    assert "tv" in dest.lower()

def test_routing_tv_auto_season():
    dest = DownloadStation.destination_for("Severance Season 2 Complete 1080p")
    assert "tv" in dest.lower()

def test_routing_movie_auto():
    dest = DownloadStation.destination_for("Dune Part Two 2024 2160p UHD BluRay")
    assert "movie" in dest.lower()

def test_routing_hdtv_is_tv():
    dest = DownloadStation.destination_for("Some Show 720p HDTV x264")
    assert "tv" in dest.lower()
