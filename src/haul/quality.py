"""
Quality scoring and selection logic for IPTorrents results.

Priority order (per Neil's spec):
  1. 2160p + HDR variant (highest tier)
  2. Balance quality score vs seeders (availability)
  3. Never pick a dead torrent (0 seeders)

Quality tiers (higher = better):
  Tier 5: 2160p + DV + Atmos + WEB-DL (best possible)
  Tier 4: 2160p + HDR + WEB-DL
  Tier 3: 2160p + WEB-DL (no HDR tag but still 4K)
  Tier 2: 2160p + WEBRip/HEVC
  Tier 1: 1080p + WEB-DL / Bluray Remux
  Tier 0: 1080p + other
  Tier -1: 720p or lower (fallback only)

Source quality (within same tier):
  AMZN > DSNP > HMAX > NF > ATVP > WEB-DL > WEBRip > HEVC > x265 > x264 > Xvid

Audio bonus:
  Atmos > TrueHD > DTS-HD > DDP5.1 > DD5.1 > AAC

HDR bonus:
  DV+HDR > DV > HDR10+ > HDR10 > SDR
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ── Quality signal patterns ────────────────────────────────────────────────────

RES_4K    = re.compile(r'\b(2160p|4K|UHD)\b', re.I)
RES_1080  = re.compile(r'\b1080p\b', re.I)
RES_720   = re.compile(r'\b720p\b', re.I)

HDR_DV    = re.compile(r'\b(DV|DoVi|Dolby.?Vision)\b', re.I)
HDR_HDR   = re.compile(r'\b(HDR10\+|HDR10|HDR)\b', re.I)
HDR_ATMOS = re.compile(r'\b(Atmos)\b', re.I)
HDR_DTS   = re.compile(r'\b(TrueHD|DTS.?HD)\b', re.I)
HDR_DDP   = re.compile(r'\b(DDP5[\. ]1|DDP)\b', re.I)

SRC_WEB_DL   = re.compile(r'\bWEB.?DL\b', re.I)
SRC_WEBRIP   = re.compile(r'\bWEB.?Rip\b', re.I)
SRC_REMUX    = re.compile(r'\bREMUX\b', re.I)
SRC_BLURAY   = re.compile(r'\b(BluRay|BDRip|BD)\b', re.I)
SRC_STREAMER = re.compile(r'\b(AMZN|DSNP|HMAX|NF|ATVP|PCOK|STAN|DSCP)\b', re.I)

CODEC_H265  = re.compile(r'\b(H\.?265|x265|HEVC|h265)\b', re.I)
CODEC_AV1   = re.compile(r'\bAV1\b', re.I)
CODEC_H264  = re.compile(r'\b(H\.?264|x264|h264)\b', re.I)

# Flags that lower score
FLAG_CAM    = re.compile(r'\b(CAM|TS|TELESYNC|TELECINE|HC\.?HDRip)\b', re.I)
FLAG_REPACK = re.compile(r'\bREPACK\b', re.I)
FLAG_DUAL   = re.compile(r'\b(DUAL|MULTI)\b', re.I)


@dataclass
class TorrentResult:
    """Parsed torrent result from IPTorrents."""
    name: str
    torrent_id: str
    download_url: str
    size_bytes: int = 0
    size_str: str = ""
    seeders: int = 0
    leechers: int = 0
    completed: int = 0
    age_hours: float = 0.0
    uploader: str = ""
    category: str = ""
    freeleech: bool = False
    # Computed
    quality_score: float = field(default=0.0, init=False)
    resolution: str = field(default="", init=False)
    hdr_type: str = field(default="", init=False)
    source: str = field(default="", init=False)
    audio: str = field(default="", init=False)
    is_cam: bool = field(default=False, init=False)

    def __post_init__(self):
        self.quality_score = score(self.name, self.seeders, self.completed)
        self.resolution = _resolution(self.name)
        self.hdr_type   = _hdr_type(self.name)
        self.source     = _source(self.name)
        self.audio      = _audio(self.name)
        self.is_cam     = bool(FLAG_CAM.search(self.name))

    @property
    def is_4k(self) -> bool:
        return bool(RES_4K.search(self.name))

    @property
    def has_hdr(self) -> bool:
        return bool(HDR_HDR.search(self.name) or HDR_DV.search(self.name))

    @property
    def has_dv(self) -> bool:
        return bool(HDR_DV.search(self.name))

    @property
    def availability_score(self) -> float:
        """0-1 score based on seeder health."""
        if self.seeders == 0:
            return 0.0
        ratio = self.seeders / max(self.leechers, 1)
        # Logarithmic — 100 seeders = good, 1000+ = excellent
        import math
        seed_score = min(math.log10(self.seeders + 1) / 3.0, 1.0)
        ratio_score = min(ratio / 10.0, 1.0)
        return (seed_score * 0.7 + ratio_score * 0.3)

    def summary(self) -> str:
        hdr = f" [{self.hdr_type}]" if self.hdr_type else ""
        return (
            f"{self.name}\n"
            f"  {self.resolution}{hdr} | {self.source} | {self.audio}\n"
            f"  {self.seeders} seeders / {self.leechers} leechers | "
            f"{self.size_str} | completed {self.completed:,}x\n"
            f"  Score: {self.quality_score:.2f}"
        )


# ── Scoring ───────────────────────────────────────────────────────────────────

def score(name: str, seeders: int, completed: int = 0) -> float:
    """
    Compute composite quality + availability score.
    Higher is better.
    """
    if seeders == 0:
        return 0.0

    s = 0.0

    # ── Resolution tier (dominant factor) ─────────────────────────────────
    if RES_4K.search(name):
        s += 1000
    elif RES_1080.search(name):
        s += 400
    elif RES_720.search(name):
        s += 100
    else:
        s += 50  # unknown / 480p

    # ── HDR/Vision bonus ───────────────────────────────────────────────────
    if HDR_DV.search(name):
        s += 150  # Dolby Vision is top tier
    if HDR_HDR.search(name):
        s += 80   # HDR10/HDR10+

    # ── Source quality ─────────────────────────────────────────────────────
    if SRC_REMUX.search(name):
        s += 120
    elif SRC_WEB_DL.search(name):
        s += 80
    elif SRC_WEBRIP.search(name):
        s += 40
    elif SRC_BLURAY.search(name):
        s += 60

    # ── Streaming source bonus ─────────────────────────────────────────────
    if SRC_STREAMER.search(name):
        s += 50

    # ── Audio bonus ────────────────────────────────────────────────────────
    if HDR_ATMOS.search(name):
        s += 40
    elif HDR_DTS.search(name):
        s += 25
    elif HDR_DDP.search(name):
        s += 15

    # ── Codec bonus ────────────────────────────────────────────────────────
    if CODEC_H265.search(name):
        s += 10  # efficient codec
    elif CODEC_AV1.search(name):
        s += 8

    # ── Penalties ──────────────────────────────────────────────────────────
    if FLAG_CAM.search(name):
        s -= 900  # cams are almost never worth it
    if FLAG_DUAL.search(name):
        s -= 20   # dubbed/multi slightly lower preference

    # ── Availability factor (seeder weighted) ──────────────────────────────
    import math
    # Log scale: 10 seeders adds ~33, 100 adds ~66, 1000 adds ~100
    seeder_bonus = math.log10(seeders + 1) * 33
    # Completed is a trust signal
    trust_bonus = math.log10(completed + 1) * 5

    s += seeder_bonus + trust_bonus

    return round(s, 2)


def select_best(results: list[TorrentResult],
                min_seeders: int = 5,
                prefer_4k_hdr: bool = True) -> TorrentResult | None:
    """
    Select the best torrent from a list of results.

    Strategy:
    1. Filter out dead torrents (< min_seeders)
    2. Filter out cams
    3. If prefer_4k_hdr: prefer 2160p+HDR candidates first
       - If best 4K+HDR has ≥ min_seeders, use it
       - If all 4K+HDR have too few seeders, fall back to best 1080p
    4. Within each group, sort by composite score
    5. Never pick something with 0 seeders
    """
    viable = [r for r in results if r.seeders >= min_seeders and not r.is_cam]
    if not viable:
        # Relax seeder threshold if nothing else
        viable = [r for r in results if r.seeders > 0 and not r.is_cam]
    if not viable:
        return None

    if prefer_4k_hdr:
        # First choice: 4K with HDR/DV
        hdr_4k = [r for r in viable if r.is_4k and r.has_hdr]
        if hdr_4k:
            return max(hdr_4k, key=lambda r: r.quality_score)

        # Second choice: 4K without explicit HDR tag (still 4K)
        k4 = [r for r in viable if r.is_4k]
        if k4:
            return max(k4, key=lambda r: r.quality_score)

    # Fallback: best available regardless of resolution
    return max(viable, key=lambda r: r.quality_score)


def explain_selection(candidates: list[TorrentResult],
                      chosen: TorrentResult | None) -> str:
    """Human-readable explanation of why a torrent was chosen."""
    if not chosen:
        return "No viable torrents found."

    lines = [f"Selected: {chosen.name}",
             f"  Reason: score={chosen.quality_score:.0f}, "
             f"seeders={chosen.seeders}, {chosen.resolution}",
             f"  HDR: {chosen.hdr_type or 'none'}, source: {chosen.source}",
             ""]

    # Show what was considered
    if len(candidates) > 1:
        lines.append(f"Considered {len(candidates)} candidates:")
        for r in sorted(candidates, key=lambda x: -x.quality_score)[:8]:
            marker = "→" if r.name == chosen.name else " "
            lines.append(
                f"  {marker} [{r.quality_score:6.0f}] {r.seeders:4d}↑ "
                f"{r.resolution:5s} {r.hdr_type:8s} {r.name[:60]}"
            )

    return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolution(name: str) -> str:
    if RES_4K.search(name):   return "2160p"
    if RES_1080.search(name): return "1080p"
    if RES_720.search(name):  return "720p"
    return "SD"

def _hdr_type(name: str) -> str:
    parts = []
    if HDR_DV.search(name):  parts.append("DV")
    if HDR_HDR.search(name): parts.append("HDR")
    return "+".join(parts)

def _source(name: str) -> str:
    if SRC_REMUX.search(name):   return "REMUX"
    if SRC_WEB_DL.search(name):  return "WEB-DL"
    if SRC_WEBRIP.search(name):  return "WEBRip"
    if SRC_BLURAY.search(name):  return "BluRay"
    return "WEB"

def _audio(name: str) -> str:
    if HDR_ATMOS.search(name): return "Atmos"
    if HDR_DTS.search(name):   return "DTS-HD"
    if HDR_DDP.search(name):   return "DDP5.1"
    return ""
