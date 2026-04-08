"""
Synology Download Station API client.
Scoped entirely to DS task management — no file system access.

API reference:
  SYNO.API.Auth          — session management
  SYNO.DownloadStation.Task — create/list/pause/resume/delete tasks

Credentials loaded from haul credential store (PQC encrypted).
"""
from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path
from typing import Any

import httpx

from src.haul.credentials import get_credential

# Download destination folders
DIR_TV     = lambda: get_credential("DS_DOWNLOAD_DIR_TV",     "/volume1/downloads/tv")
DIR_MOVIES = lambda: get_credential("DS_DOWNLOAD_DIR_MOVIES", "/volume1/downloads/movies")
DIR_OTHER  = lambda: get_credential("DS_DOWNLOAD_DIR_OTHER",  "/volume1/downloads/other")


def _host() -> str:
    h = get_credential("SYNOLOGY_HOST", "")
    if not h:
        raise RuntimeError("SYNOLOGY_HOST not configured. Run: haul setup")
    return h.rstrip("/")


class DownloadStation:
    """
    Synology Download Station API client.
    Session-based — authenticates on connect, invalidates on close.
    """

    def __init__(self, host: str | None = None,
                 username: str | None = None,
                 password: str | None = None):
        self.host     = (host     or _host()).rstrip("/")
        self.username = username  or get_credential("SYNOLOGY_USER", "")
        self.password = password  or get_credential("SYNOLOGY_PASS", "")
        self._sid: str | None = None
        self._client = httpx.Client(
            verify=False,  # many home Synology NAS use self-signed certs
            timeout=30,
        )

    def __enter__(self) -> "DownloadStation":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.disconnect()

    def connect(self) -> None:
        """Authenticate with DSM and get session ID."""
        resp = self._client.get(
            f"{self.host}/webapi/auth.cgi",
            params={
                "api":     "SYNO.API.Auth",
                "version": "3",
                "method":  "login",
                "account": self.username,
                "passwd":  self.password,
                "session": "DownloadStation",
                "format":  "cookie",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            code = data.get("error", {}).get("code", "unknown")
            raise RuntimeError(f"Synology auth failed (code {code}). Check credentials.")
        self._sid = data["data"]["sid"]

    def disconnect(self) -> None:
        """Invalidate DSM session."""
        if self._sid:
            try:
                self._client.get(
                    f"{self.host}/webapi/auth.cgi",
                    params={
                        "api": "SYNO.API.Auth", "version": "1",
                        "method": "logout", "session": "DownloadStation",
                        "_sid": self._sid,
                    },
                )
            except Exception:
                pass
            self._sid = None
        self._client.close()

    def _api(self, endpoint: str, params: dict) -> dict:
        """Make an authenticated API call."""
        if not self._sid:
            raise RuntimeError("Not connected. Use with-statement.")
        params["_sid"] = self._sid
        resp = self._client.get(
            f"{self.host}/webapi/{endpoint}",
            params=params,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Task management ───────────────────────────────────────────────────────

    def add_torrent_file(self, torrent_bytes: bytes,
                         destination: str,
                         filename: str = "task.torrent") -> dict[str, Any]:
        """
        Add a .torrent file to Download Station.
        destination: absolute path on NAS volume (e.g. /volume1/downloads/movies)
        """
        with tempfile.NamedTemporaryFile(suffix=".torrent", delete=False) as tmp:
            tmp.write(torrent_bytes)
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as f:
                resp = self._client.post(
                    f"{self.host}/webapi/DownloadStation/task.cgi",
                    data={
                        "api":         "SYNO.DownloadStation.Task",
                        "version":     "1",
                        "method":      "create",
                        "destination": destination,
                        "_sid":        self._sid,
                    },
                    files={"file": (filename, f, "application/x-bittorrent")},
                )
            resp.raise_for_status()
            return resp.json()
        finally:
            os.unlink(tmp_path)

    def add_magnet(self, magnet_uri: str, destination: str) -> dict[str, Any]:
        """Add a magnet link to Download Station."""
        return self._api("DownloadStation/task.cgi", {
            "api":         "SYNO.DownloadStation.Task",
            "version":     "1",
            "method":      "create",
            "uri":         magnet_uri,
            "destination": destination,
        })

    def list_tasks(self) -> list[dict[str, Any]]:
        """List all current Download Station tasks."""
        data = self._api("DownloadStation/task.cgi", {
            "api":        "SYNO.DownloadStation.Task",
            "version":    "1",
            "method":     "list",
            "additional": "transfer,detail",
        })
        if not data.get("success"):
            return []
        return [
            {
                "id":          t["id"],
                "title":       t["title"],
                "status":      t["status"],
                "size":        t.get("size", 0),
                "downloaded":  t.get("additional", {}).get("transfer", {}).get("size_downloaded", 0),
                "speed_dl":    t.get("additional", {}).get("transfer", {}).get("speed_download", 0),
                "destination": t.get("additional", {}).get("detail", {}).get("destination", ""),
            }
            for t in data.get("data", {}).get("tasks", [])
        ]

    def pause_task(self, task_id: str) -> dict:
        return self._api("DownloadStation/task.cgi", {
            "api": "SYNO.DownloadStation.Task", "version": "1",
            "method": "pause", "id": task_id,
        })

    def resume_task(self, task_id: str) -> dict:
        return self._api("DownloadStation/task.cgi", {
            "api": "SYNO.DownloadStation.Task", "version": "1",
            "method": "resume", "id": task_id,
        })

    def delete_task(self, task_id: str, force: bool = False) -> dict:
        return self._api("DownloadStation/task.cgi", {
            "api": "SYNO.DownloadStation.Task", "version": "1",
            "method": "delete", "id": task_id,
            "force_complete": str(force).lower(),
        })

    def get_info(self) -> dict[str, Any]:
        """Get Download Station info (version, status)."""
        return self._api("DownloadStation/info.cgi", {
            "api": "SYNO.DownloadStation.Info", "version": "1",
            "method": "getinfo",
        })

    # ── Smart destination routing ─────────────────────────────────────────────

    @staticmethod
    def destination_for(name: str, media_type: str = "auto") -> str:
        """
        Route to correct folder based on media type or name pattern.
        media_type: 'movie', 'tv', 'auto'
        """
        if media_type == "movie":
            return DIR_MOVIES()
        if media_type == "tv":
            return DIR_TV()

        # Auto-detect from name
        tv_patterns = [
            r'S\d{2}E\d{2}',          # S01E01
            r'\d{1,2}x\d{2}',          # 1x01
            r'Season\s*\d+',            # Season 1
            r'Complete\s*Series',
        ]
        import re
        for p in tv_patterns:
            if re.search(p, name, re.I):
                return DIR_TV()

        return DIR_MOVIES()
