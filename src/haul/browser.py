"""
IPTorrents browser session using Playwright.
HttpOnly cookies are preserved in a persistent browser profile.
Login once, reuse session across all searches.
"""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright, BrowserContext, Page

from src.haul.quality import TorrentResult

BASE_URL = "https://iptorrents.com"

# Session stored in ~/.haul/session/
def _session_dir() -> Path:
    import os
    d = Path(os.getenv("HAUL_DATA_DIR", str(Path.home() / ".haul"))) / "session"
    d.mkdir(parents=True, exist_ok=True)
    return d


class IPTSession:
    """
    Persistent Playwright browser session for IPTorrents.
    Stores cookies/session to disk — survives process restarts.
    Only re-authenticates when session expires.
    """

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def __aenter__(self) -> "IPTSession":
        await self.start()
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        # Persistent context — saves cookies, localStorage, etc.
        self._context = await self._browser.new_context(
            storage_state=str(_session_dir() / "storage.json")
            if (_session_dir() / "storage.json").exists() else None,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        self._page = await self._context.new_page()

    async def close(self) -> None:
        if self._context:
            await self._context.storage_state(
                path=str(_session_dir() / "storage.json")
            )
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def is_logged_in(self) -> bool:
        """Check if current session is authenticated."""
        await self._page.goto(f"{BASE_URL}/t", wait_until="domcontentloaded")
        return "login" not in self._page.url.lower() and \
               await self._page.query_selector("a[href='/upload.php']") is not None

    async def login(self, username: str, password: str) -> bool:
        """Log in to IPTorrents. Returns True on success."""
        await self._page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")

        # Fill login form
        await self._page.fill("input[name='username'], input[type='text']", username)
        await self._page.fill("input[name='password'], input[type='password']", password)
        await self._page.click("input[type='submit'], button[type='submit']")
        await self._page.wait_for_load_state("domcontentloaded")

        success = await self.is_logged_in()
        if success:
            # Save session immediately
            await self._context.storage_state(
                path=str(_session_dir() / "storage.json")
            )
        return success

    async def ensure_logged_in(self, username: str, password: str) -> None:
        """Ensure we have a valid session, login if needed."""
        if not await self.is_logged_in():
            ok = await self.login(username, password)
            if not ok:
                raise RuntimeError("IPTorrents login failed. Check credentials.")

    # ── Search ────────────────────────────────────────────────────────────────

    async def search(self, query: str, category_id: int | None = None,
                     max_pages: int = 3) -> list[TorrentResult]:
        """
        Search IPTorrents and return parsed results sorted by seeders.
        Fetches up to max_pages pages to get all quality variants.
        """
        results: list[TorrentResult] = []
        seen_ids: set[str] = set()

        for page_num in range(1, max_pages + 1):
            url = f"{BASE_URL}/t?q={query}&qf=all&o=seeders"
            if category_id:
                url += f"&cat={category_id}"
            if page_num > 1:
                url += f"&p={page_num}#torrents"

            await self._page.goto(url, wait_until="domcontentloaded")

            page_results = await self._parse_results()
            new_results = [r for r in page_results if r.torrent_id not in seen_ids]

            if not new_results:
                break  # No new results, stop paging

            results.extend(new_results)
            seen_ids.update(r.torrent_id for r in new_results)

            # If first page has fewer than 50 results, no point checking page 2
            if len(page_results) < 50:
                break

        return results

    async def _parse_results(self) -> list[TorrentResult]:
        """Parse torrent rows from current page."""
        results = []

        rows = await self._page.eval_on_selector_all(
            "tr",
            """rows => {
                return rows
                    .filter(r => r.querySelector('a[href*="/t/"]') &&
                                 r.querySelector('a[href*="download.php"]'))
                    .map(r => {
                        const nameEl = r.querySelector('a[href*="/t/"]');
                        const dlEl   = r.querySelector('a[href*="download.php"]');
                        const cells  = Array.from(r.querySelectorAll('td'))
                                           .map(td => td.innerText.trim());
                        const idMatch = dlEl?.href?.match(/download\\.php\\/(\\d+)/);
                        const metaEl = r.querySelector('.tt');
                        const meta   = metaEl?.innerText || '';

                        // Find size, completed, seeders, leechers from cells
                        // Order: ... | comments | size | files | completed | seeders | leechers
                        const numCells = cells.filter(c => /^[\\d.]+/.test(c));

                        return {
                            name:        nameEl?.innerText?.trim() || '',
                            href:        nameEl?.href || '',
                            dl_url:      dlEl?.href || '',
                            torrent_id:  idMatch?.[1] || '',
                            meta:        meta,
                            cells:       cells,
                            freeleech:   r.innerText.includes('FreeLeech'),
                        };
                    })
                    .filter(r => r.torrent_id && r.name &&
                                 !r.name.includes('Staff Picks') &&
                                 !r.name.includes('HOT RIGHT NOW'));
            }"""
        )

        for row in rows:
            try:
                result = self._parse_row(row)
                if result:
                    results.append(result)
            except Exception:
                continue

        return results

    def _parse_row(self, row: dict) -> TorrentResult | None:
        """Parse a single row dict into a TorrentResult."""
        name = row.get("name", "").strip()
        if not name or len(name) < 5:
            return None

        torrent_id = row.get("torrent_id", "")
        dl_url = row.get("dl_url", "")

        # Parse numeric fields from cells
        cells = row.get("cells", [])
        nums = []
        for c in cells:
            c = c.strip().replace(",", "")
            # Match pure numbers or sizes like "6.43 GB", "647 MB"
            if re.match(r'^[\d.]+\s*(GB|MB|KB|TB)?$', c, re.I):
                nums.append(c)

        # Try to extract size, completed, seeders, leechers from tail of cells
        # IPT format: ... | comments | size | files | completed | seeders | leechers
        size_str = ""
        seeders = leechers = completed = 0

        # Find size (has GB/MB)
        for c in cells:
            if re.search(r'\d+\.?\d*\s*(GB|MB)', c, re.I):
                size_str = c.strip()
                break

        # Last 3 pure integers = completed, seeders, leechers
        int_cells = [c.strip() for c in cells
                     if re.match(r'^\d+$', c.strip()) and len(c.strip()) > 0]
        if len(int_cells) >= 3:
            try:
                completed = int(int_cells[-3])
                seeders   = int(int_cells[-2])
                leechers  = int(int_cells[-1])
            except (ValueError, IndexError):
                pass
        elif len(int_cells) >= 2:
            try:
                seeders  = int(int_cells[-2])
                leechers = int(int_cells[-1])
            except (ValueError, IndexError):
                pass

        # Parse size to bytes
        size_bytes = _parse_size(size_str)

        # Parse age from meta
        meta = row.get("meta", "")
        age_hours = _parse_age(meta)
        uploader = _parse_uploader(meta)

        return TorrentResult(
            name=name,
            torrent_id=torrent_id,
            download_url=dl_url,
            size_bytes=size_bytes,
            size_str=size_str,
            seeders=seeders,
            leechers=leechers,
            completed=completed,
            age_hours=age_hours,
            uploader=uploader,
            freeleech=row.get("freeleech", False),
        )

    async def download_torrent(self, torrent_id: str) -> bytes:
        """Download .torrent file bytes for a given torrent ID."""
        url = f"{BASE_URL}/download.php/{torrent_id}/{torrent_id}.torrent"
        response = await self._page.request.get(url)
        if response.status != 200:
            raise RuntimeError(f"Download failed: HTTP {response.status}")
        return await response.body()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_size(size_str: str) -> int:
    """Parse '6.43 GB' → bytes."""
    m = re.match(r'([\d.]+)\s*(TB|GB|MB|KB)', size_str, re.I)
    if not m:
        return 0
    val = float(m.group(1))
    unit = m.group(2).upper()
    return int(val * {"TB": 1e12, "GB": 1e9, "MB": 1e6, "KB": 1e3}[unit])


def _parse_age(meta: str) -> float:
    """Parse '13.7 hours ago' or '2.8 days ago' → hours."""
    m = re.search(r'([\d.]+)\s*(hours?|days?|minutes?|weeks?)', meta, re.I)
    if not m:
        return 0.0
    val = float(m.group(1))
    unit = m.group(2).lower()
    if "minute" in unit:   return val / 60
    if "hour" in unit:     return val
    if "day" in unit:      return val * 24
    if "week" in unit:     return val * 168
    return 0.0


def _parse_uploader(meta: str) -> str:
    m = re.search(r'by\s+(\w+)', meta, re.I)
    return m.group(1) if m else ""
