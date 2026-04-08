"""
Query normalization — translates natural language media requests
into clean search strings IPTorrents understands.

Handles:
  "Download season 5 episode 1 of the boys"  → "The Boys S05E01"
  "the boys s5e1"                             → "The Boys S05E01"
  "boys season 5 ep 1"                        → "The Boys S05E01"
  "dune part two"                             → "Dune Part Two"
  "latest episode of severance"               → "Severance"  (no ep = latest)
  "severance s02"                             → "Severance S02"  (full season)
  "the last of us season 2"                   → "The Last of Us S02"
  "avengers endgame 4k"                       → "Avengers Endgame 2160p"
  "endgame in 4k hdr"                         → "Avengers Endgame 2160p HDR"  (title lookup needed)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# ── Patterns ──────────────────────────────────────────────────────────────────

# "season 5 episode 1" / "season 5, episode 1" / "s5e1" / "S05E01" / "5x01"
EP_LONG  = re.compile(
    r'season\s*(\d+)\s*[,\s]*ep(?:isode)?\s*(\d+)', re.I
)
EP_SHORT = re.compile(r'\bs(\d{1,2})\s*e(\d{1,2})\b', re.I)
EP_ALT   = re.compile(r'\b(\d{1,2})x(\d{2})\b')           # 1x01
EP_EP    = re.compile(r'\bep(?:isode)?\s*(\d+)\b', re.I)  # episode 3 (no season)

# "season 5" (full season, no episode)
SEASON_ONLY = re.compile(r'season\s*(\d+)', re.I)
S_ONLY      = re.compile(r'\bs(\d{1,2})\b(?!\s*e)', re.I)

# Quality hints in natural language
Q_4K    = re.compile(r'\b(4k|4096|2160p?|uhd)\b', re.I)
Q_1080  = re.compile(r'\b(1080p?|full.?hd)\b', re.I)
Q_720   = re.compile(r'\b720p?\b', re.I)
Q_HDR   = re.compile(r'\b(hdr|dolby.?vision|dv)\b', re.I)
Q_REMUX = re.compile(r'\bremux\b', re.I)

# Words to strip from title before searching
STRIP_WORDS = re.compile(
    r'\b(download|get me|find me|i want|i need|can you get|please|'
    r'in\s+4k|in\s+1080p|in\s+uhd|in\s+hdr|full\s+hd|'
    r'the\s+latest|latest\s+episode\s+of|episode\s+of|'
    r'torrent|bluray|blu.ray|web.?dl|webrip)\b',
    re.I
)

# Noise phrases
NOISE = re.compile(
    r'\b(please|thanks|thank you|could you|would you|can you|'
    r'go ahead and|for me|right now|asap)\b', re.I
)


@dataclass
class ParsedQuery:
    """Structured result of query normalization."""
    title: str              # Cleaned title (e.g. "The Boys")
    season: int | None      # Season number or None
    episode: int | None     # Episode number or None
    season_pack: bool       # True if full season requested (no episode)
    quality_hint: str       # "2160p" / "1080p" / "720p" / ""
    hdr_hint: bool          # User asked for HDR/4K HDR
    remux_hint: bool        # User asked for REMUX
    media_type: str         # "tv" / "movie" / "auto"
    search_string: str      # Final string to send to IPTorrents

    def __str__(self) -> str:
        return self.search_string


def normalize(raw_query: str) -> ParsedQuery:
    """
    Normalize a natural language query into a clean IPTorrents search string.

    Examples:
      "Download season 5 episode 1 of The Boys"  → ParsedQuery(search="The Boys S05E01")
      "the boys s5e1 4k"                          → ParsedQuery(search="The Boys S05E01 2160p")
      "dune part two in hdr"                      → ParsedQuery(search="Dune Part Two", hdr_hint=True)
      "the last of us season 2"                   → ParsedQuery(search="The Last of Us S02")
    """
    q = raw_query.strip()

    # ── Extract quality hints before stripping ────────────────────────────────
    quality_hint = ""
    hdr_hint     = bool(Q_HDR.search(q))
    remux_hint   = bool(Q_REMUX.search(q))

    if Q_4K.search(q):
        quality_hint = "2160p"
    elif Q_1080.search(q):
        quality_hint = "1080p"
    elif Q_720.search(q):
        quality_hint = "720p"

    # ── Extract episode info ──────────────────────────────────────────────────
    season = episode = None
    season_pack = False

    m = EP_LONG.search(q)
    if m:
        season, episode = int(m.group(1)), int(m.group(2))
        q = EP_LONG.sub("", q)
    else:
        m = EP_SHORT.search(q)
        if m:
            season, episode = int(m.group(1)), int(m.group(2))
            q = EP_SHORT.sub("", q)
        else:
            m = EP_ALT.search(q)
            if m:
                season, episode = int(m.group(1)), int(m.group(2))
                q = EP_ALT.sub("", q)

    # Season-only (no episode) → season pack
    if season is None:
        m = SEASON_ONLY.search(q)
        if m:
            season = int(m.group(1))
            season_pack = True
            q = SEASON_ONLY.sub("", q)
        else:
            m = S_ONLY.search(q)
            if m:
                season = int(m.group(1))
                season_pack = True
                q = S_ONLY.sub("", q)
    elif episode is not None:
        # Remove standalone season refs that weren't part of episode pattern
        q = SEASON_ONLY.sub("", q)

    # ── Strip noise words and quality tokens from title ───────────────────────
    q = NOISE.sub("", q)
    q = STRIP_WORDS.sub("", q)
    q = Q_4K.sub("", q)
    q = Q_1080.sub("", q)
    q = Q_720.sub("", q)
    q = Q_HDR.sub("", q)
    q = Q_REMUX.sub("", q)

    # Handle "X of Y" → strip "of" preposition leftovers
    q = re.sub(r'\bof\b', '', q, flags=re.I)

    # Clean up whitespace, punctuation
    q = re.sub(r'[,;]+', ' ', q)
    q = re.sub(r'\s+', ' ', q).strip()

    # ── Title-case the title ──────────────────────────────────────────────────
    # Preserve known acronyms and short words
    LOWER_WORDS = {'a','an','the','and','but','or','for','nor','on','at',
                   'to','by','in','of','up','as','is','it'}
    words = q.split()
    if words:
        titled = []
        for i, w in enumerate(words):
            if i == 0 or w.lower() not in LOWER_WORDS:
                titled.append(w.capitalize())
            else:
                titled.append(w.lower())
        q = " ".join(titled)

    title = q.strip()

    # ── Detect media type ─────────────────────────────────────────────────────
    media_type = "auto"
    if season is not None or episode is not None:
        media_type = "tv"

    # ── Build search string ───────────────────────────────────────────────────
    parts = [title]

    if season is not None and episode is not None:
        parts.append(f"S{season:02d}E{episode:02d}")
    elif season is not None and season_pack:
        parts.append(f"S{season:02d}")

    if quality_hint:
        parts.append(quality_hint)

    search_string = " ".join(p for p in parts if p).strip()

    return ParsedQuery(
        title=title,
        season=season,
        episode=episode,
        season_pack=season_pack,
        quality_hint=quality_hint,
        hdr_hint=hdr_hint,
        remux_hint=remux_hint,
        media_type=media_type,
        search_string=search_string,
    )


def normalize_str(raw_query: str) -> str:
    """Convenience — just return the search string."""
    return normalize(raw_query).search_string
