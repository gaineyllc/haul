"""Tests for query normalization — natural language → search string."""
import pytest
from src.haul.query import normalize, normalize_str


# ── Episode parsing ───────────────────────────────────────────────────────────

def test_season_episode_long_form():
    r = normalize("Download season 5 episode 1 of The Boys")
    assert r.season == 5
    assert r.episode == 1
    assert "S05E01" in r.search_string
    assert "The Boys" in r.search_string

def test_season_episode_short_form():
    r = normalize("the boys s5e1")
    assert r.season == 5
    assert r.episode == 1
    assert "S05E01" in r.search_string

def test_season_episode_standard():
    r = normalize("The Boys S05E01")
    assert r.season == 5
    assert r.episode == 1
    assert "S05E01" in r.search_string

def test_season_episode_alt_format():
    r = normalize("show 2x04")
    assert r.season == 2
    assert r.episode == 4
    assert "S02E04" in r.search_string

def test_season_episode_verbose():
    r = normalize("can you get me season 3, episode 7 of severance please")
    assert r.season == 3
    assert r.episode == 7
    assert "S03E07" in r.search_string
    assert "Severance" in r.search_string

def test_zero_padding():
    r = normalize("show s1e2")
    assert "S01E02" in r.search_string

def test_double_digit_episode():
    r = normalize("show S02E12")
    assert "S02E12" in r.search_string


# ── Season pack (no episode) ──────────────────────────────────────────────────

def test_season_only_long():
    r = normalize("The Last of Us season 2")
    assert r.season == 2
    assert r.episode is None
    assert r.season_pack is True
    assert "S02" in r.search_string

def test_season_only_short():
    r = normalize("severance s02")
    assert r.season == 2
    assert r.season_pack is True
    assert "S02" in r.search_string


# ── Quality hints ─────────────────────────────────────────────────────────────

def test_4k_translates_to_2160p():
    r = normalize("the boys s05e01 4k")
    assert r.quality_hint == "2160p"
    assert "2160p" in r.search_string

def test_uhd_translates_to_2160p():
    r = normalize("avengers endgame UHD")
    assert r.quality_hint == "2160p"

def test_1080p_preserved():
    r = normalize("movie 1080p")
    assert r.quality_hint == "1080p"
    assert "1080p" in r.search_string

def test_hdr_hint_detected():
    r = normalize("dune part two in hdr")
    assert r.hdr_hint is True

def test_dolby_vision_hint():
    r = normalize("movie dolby vision")
    assert r.hdr_hint is True


# ── Media type detection ──────────────────────────────────────────────────────

def test_tv_detected_by_episode():
    r = normalize("the boys s05e01")
    assert r.media_type == "tv"

def test_movie_has_auto_type():
    r = normalize("dune part two 2160p")
    assert r.media_type == "auto"  # no episode = unknown, caller decides


# ── Noise stripping ───────────────────────────────────────────────────────────

def test_strips_download_word():
    r = normalize("download the boys s05e01")
    assert "download" not in r.search_string.lower()
    assert "Boys" in r.search_string

def test_strips_please():
    r = normalize("please get me severance s02e03")
    assert "please" not in r.search_string.lower()

def test_strips_get_me():
    r = normalize("get me the boys s05e01")
    assert "get" not in r.search_string.lower() or "Boys" in r.search_string

def test_strips_find_me():
    r = normalize("find me dune 2160p")
    assert "find" not in r.search_string.lower()

def test_strips_in_4k():
    r = normalize("the boys in 4k s05e01")
    assert "in" not in r.search_string or "Boys" in r.search_string
    assert "4k" not in r.search_string.lower()
    assert "2160p" in r.search_string


# ── Title casing ──────────────────────────────────────────────────────────────

def test_title_case_applied():
    r = normalize("the boys s05e01")
    assert r.search_string.startswith("The Boys")

def test_title_case_multi_word():
    r = normalize("the last of us s02e01")
    assert "The Last" in r.search_string


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_already_formatted():
    assert "S05E01" in normalize_str("The Boys S05E01")

def test_movie_no_episode():
    r = normalize("Oppenheimer 2023")
    assert r.season is None
    assert r.episode is None

def test_empty_quality():
    r = normalize("The Boys S05E01")
    assert r.quality_hint == ""

def test_normalize_str_convenience():
    result = normalize_str("season 2 episode 4 of severance")
    assert "S02E04" in result
    assert "Severance" in result
