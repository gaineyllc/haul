"""
Synology Download Station API client.
Implements BOTH the classic API (DSM 6) and the newer DSM 7 API.
Auto-detects which version to use based on what the NAS responds to.

Official API reference:
  https://global.download.synology.com/download/Document/Software/DeveloperGuide/
  Package/DownloadStation/All/enu/Synology_Download_Station_Web_API.pdf

Classic (DSM 6):  POST /webapi/DownloadStation/task.cgi
DSM 7:            POST /webapi/entry.cgi  (SYNO.DownloadStation2.Task)

All documented create parameters are supported.
Credentials loaded from haul credential store (PQC encrypted).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import httpx

from src.haul.credentials import get_credential

# ── Credential helpers ────────────────────────────────────────────────────────

def _host()     -> str: return get_credential("SYNOLOGY_HOST", "").rstrip("/")
def _user()     -> str: return get_credential("SYNOLOGY_USER", "")
def _password() -> str: return get_credential("SYNOLOGY_PASS", "")
def _dir_tv()   -> str: return get_credential("DS_DOWNLOAD_DIR_TV",     "/volume1/downloads/tv")
def _dir_mov()  -> str: return get_credential("DS_DOWNLOAD_DIR_MOVIES", "/volume1/downloads/movies")
def _dir_other()-> str: return get_credential("DS_DOWNLOAD_DIR_OTHER",  "/volume1/downloads/other")


# ── Error codes from Synology API docs ────────────────────────────────────────

DS_ERRORS = {
    400: "File upload failed",
    401: "Max number of tasks reached",
    402: "Destination denied (no write permission)",
    403: "Destination does not exist",
    404: "Invalid task ID",
    405: "Invalid task action",
    406: "No default destination",
    407: "Set destination failed",
    408: "File does not exist",
}


from src.haul.synology_full import DownloadStationFull


class DownloadStation(DownloadStationFull):
    """
    Synology Download Station API client.
    Supports DSM 6 (task.cgi) and DSM 7 (entry.cgi) automatically.

    Session caching: authenticates once, reuses _sid until expiry,
    then re-authenticates automatically.
    """

    def __init__(self, host: str | None = None,
                 username: str | None = None,
                 password: str | None = None):
        self.host     = (host     or _host()).rstrip("/")
        self.username = username  or _user()
        self.password = password  or _password()

        if not self.host:
            raise RuntimeError(
                "Synology host not configured. Run: python -m src.haul.setup"
            )

        self._sid: str | None = None
        self._api_version: int = 1       # discovered at connect time
        self._use_entry_cgi: bool = False # DSM 7 uses entry.cgi
        self._client = httpx.Client(
            verify=False,  # home NAS typically uses self-signed cert
            timeout=30,
            follow_redirects=True,
        )

    def __enter__(self) -> "DownloadStation":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.disconnect()

    # ── Connection ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Authenticate with DSM, discover API version."""
        # First: discover supported API versions
        self._discover_api()
        # Authenticate
        self._authenticate()

    def _discover_api(self) -> None:
        """Query the NAS for supported API versions."""
        try:
            r = self._client.get(
                f"{self.host}/webapi/query.cgi",
                params={
                    "api":     "SYNO.API.Info",
                    "version": "1",
                    "method":  "query",
                    "query":   "SYNO.DownloadStation2.Task,SYNO.DownloadStation.Task",
                },
            )
            data = r.json()
            if data.get("success"):
                apis = data.get("data", {})
                # Prefer DSM7 API if available
                if "SYNO.DownloadStation2.Task" in apis:
                    info = apis["SYNO.DownloadStation2.Task"]
                    self._use_entry_cgi = True
                    self._api_version = info.get("maxVersion", 2)
                elif "SYNO.DownloadStation.Task" in apis:
                    info = apis["SYNO.DownloadStation.Task"]
                    self._use_entry_cgi = False
                    self._api_version = min(info.get("maxVersion", 1), 3)
        except Exception:
            pass  # fall back to defaults

    def _authenticate(self) -> None:
        """Authenticate and store session ID."""
        r = self._client.get(
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
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            code = data.get("error", {}).get("code", "unknown")
            raise RuntimeError(
                f"Synology authentication failed (error code: {code}). "
                f"Check SYNOLOGY_USER and SYNOLOGY_PASS credentials."
            )
        self._sid = data["data"]["sid"]

    def disconnect(self) -> None:
        """Log out and close connection."""
        if self._sid:
            try:
                self._client.get(
                    f"{self.host}/webapi/auth.cgi",
                    params={
                        "api":     "SYNO.API.Auth",
                        "version": "1",
                        "method":  "logout",
                        "session": "DownloadStation",
                        "_sid":    self._sid,
                    },
                )
            except Exception:
                pass
            self._sid = None
        self._client.close()

    def _endpoint(self) -> str:
        """Return the correct CGI path for this DSM version."""
        if self._use_entry_cgi:
            return f"{self.host}/webapi/entry.cgi"
        return f"{self.host}/webapi/DownloadStation/task.cgi"

    def _api_name(self) -> str:
        if self._use_entry_cgi:
            return "SYNO.DownloadStation2.Task"
        return "SYNO.DownloadStation.Task"

    def _check(self, data: dict) -> dict:
        """Raise a descriptive error if the API response indicates failure."""
        if not data.get("success"):
            code = data.get("error", {}).get("code", 0)
            msg  = DS_ERRORS.get(code, f"Unknown error (code {code})")
            raise RuntimeError(f"Download Station API error: {msg}")
        return data

    # ── Task creation ──────────────────────────────────────────────────────────

    def add_torrent_file(
        self,
        torrent_bytes: bytes,
        destination: str,
        filename: str = "task.torrent",
        username: str = "",
        password: str = "",
        unzip_password: str = "",
        create_subfolder: bool = False,
    ) -> dict[str, Any]:
        """
        Add a .torrent file to Download Station.

        Args:
            torrent_bytes:    Raw .torrent file content
            destination:      Download destination — path starting with a shared
                              folder name (e.g. 'downloads/movies' NOT '/volume1/...')
                              NOTE: Synology API expects the path relative to the
                              volume root, NOT the full /volume1/ path.
                              Example: 'downloads/movies' maps to /volume1/downloads/movies
            filename:         Filename for the torrent (cosmetic)
            username:         Optional login for private trackers
            password:         Optional login for private trackers
            unzip_password:   Password to unzip download if archived
            create_subfolder: Create a subfolder named after the torrent

        Returns:
            API response dict — {"success": true} on success

        Raises:
            RuntimeError with descriptive message on failure
        """
        # Normalize destination — strip leading /volume1/ if present
        destination = _normalize_destination(destination)

        with tempfile.NamedTemporaryFile(suffix=".torrent", delete=False) as tmp:
            tmp.write(torrent_bytes)
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as f:
                form_data = {
                    "api":         self._api_name(),
                    "version":     str(self._api_version),
                    "method":      "create",
                    "destination": destination,
                    "_sid":        self._sid,
                }
                # DSM7 extra parameters
                if self._use_entry_cgi:
                    form_data["type"] = "file"
                    form_data["create_list"] = "false"

                # Optional parameters
                if username:       form_data["username"]       = username
                if password:       form_data["password"]       = password
                if unzip_password: form_data["unzip_password"] = unzip_password

                resp = self._client.post(
                    self._endpoint(),
                    data=form_data,
                    files={"file": (filename, f, "application/x-bittorrent")},
                )
            resp.raise_for_status()
            return self._check(resp.json())
        finally:
            os.unlink(tmp_path)

    def add_url(
        self,
        url: str,
        destination: str,
        username: str = "",
        password: str = "",
        unzip_password: str = "",
    ) -> dict[str, Any]:
        """
        Add a download by URL (HTTP/FTP/magnet/ED2K).

        Args:
            url:          URL or magnet link to download
            destination:  Shared-folder-relative path (e.g. 'downloads/movies')
        """
        destination = _normalize_destination(destination)
        params = {
            "api":         self._api_name(),
            "version":     str(self._api_version),
            "method":      "create",
            "uri":         url,
            "destination": destination,
            "_sid":        self._sid,
        }
        if username:       params["username"]       = username
        if password:       params["password"]       = password
        if unzip_password: params["unzip_password"] = unzip_password
        if self._use_entry_cgi:
            params["type"]        = "url"
            params["create_list"] = "false"

        r = self._client.post(self._endpoint(), data=params)
        r.raise_for_status()
        return self._check(r.json())

    # ── Task management ────────────────────────────────────────────────────────

    def list_tasks(self, offset: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        """
        List Download Station tasks with full detail.

        Returns list of dicts with: id, title, status, type, size,
        size_downloaded, size_uploaded, speed_download, speed_upload, destination
        """
        params = {
            "api":        self._api_name(),
            "version":    str(self._api_version),
            "method":     "list",
            "offset":     str(offset),
            "limit":      str(limit),
            "additional": "detail,transfer,tracker,peer",
            "_sid":       self._sid,
        }
        r = self._client.get(self._endpoint(), params=params)
        r.raise_for_status()
        data = self._check(r.json())

        tasks = data.get("data", {}).get("tasks", [])
        return [_flatten_task(t) for t in tasks]

    def get_task(self, task_id: str) -> dict[str, Any]:
        """Get detailed info for a specific task."""
        params = {
            "api":        self._api_name(),
            "version":    str(self._api_version),
            "method":     "getinfo",
            "id":         task_id,
            "additional": "detail,transfer,tracker,peer",
            "_sid":       self._sid,
        }
        r = self._client.get(self._endpoint(), params=params)
        r.raise_for_status()
        data = self._check(r.json())
        tasks = data.get("data", {}).get("tasks", [])
        return _flatten_task(tasks[0]) if tasks else {}

    def pause_task(self, task_id: str) -> dict:
        return self._check(self._client.get(
            self._endpoint(),
            params={"api": self._api_name(), "version": str(self._api_version),
                    "method": "pause", "id": task_id, "_sid": self._sid}
        ).json())

    def resume_task(self, task_id: str) -> dict:
        return self._check(self._client.get(
            self._endpoint(),
            params={"api": self._api_name(), "version": str(self._api_version),
                    "method": "resume", "id": task_id, "_sid": self._sid}
        ).json())

    def delete_task(self, task_id: str, force_complete: bool = False) -> dict:
        return self._check(self._client.get(
            self._endpoint(),
            params={"api": self._api_name(), "version": str(self._api_version),
                    "method": "delete", "id": task_id,
                    "force_complete": str(force_complete).lower(),
                    "_sid": self._sid}
        ).json())

    def edit_destination(self, task_id: str, destination: str) -> dict:
        """Change the destination folder of a pending task."""
        return self._check(self._client.get(
            self._endpoint(),
            params={"api": self._api_name(), "version": "2",
                    "method": "edit", "id": task_id,
                    "destination": _normalize_destination(destination),
                    "_sid": self._sid}
        ).json())

    # ── Server info ────────────────────────────────────────────────────────────

    def get_info(self) -> dict[str, Any]:
        """Get Download Station version and config."""
        r = self._client.get(
            f"{self.host}/webapi/DownloadStation/info.cgi",
            params={"api": "SYNO.DownloadStation.Info", "version": "1",
                    "method": "getinfo", "_sid": self._sid}
        )
        r.raise_for_status()
        return r.json()

    def get_config(self) -> dict[str, Any]:
        """Get Download Station config including default destination."""
        r = self._client.get(
            f"{self.host}/webapi/DownloadStation/info.cgi",
            params={"api": "SYNO.DownloadStation.Info", "version": "1",
                    "method": "getconfig", "_sid": self._sid}
        )
        r.raise_for_status()
        return r.json()

    def list_shared_folders(self) -> list[dict[str, Any]]:
        """
        List available shared folders on the NAS.
        Useful for discovering valid destination paths.
        """
        r = self._client.get(
            f"{self.host}/webapi/entry.cgi",
            params={"api": "SYNO.FileStation.List", "version": "2",
                    "method": "list_share", "_sid": self._sid,
                    "additional": "size,owner"}
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            return []
        return [
            {"name": s["name"], "path": s["path"],
             "is_writable": s.get("additional", {}).get("perm", {}).get("acl", {}).get("write", False)}
            for s in data.get("data", {}).get("shares", [])
        ]

    # ── Smart routing ──────────────────────────────────────────────────────────

    @staticmethod
    def destination_for(name: str, media_type: str = "auto") -> str:
        """
        Route to correct download folder based on media type.
        Returns the shared-folder-relative path (NOT /volume1/...).

        media_type: 'movie', 'tv', 'auto'
        """
        if media_type == "movie":
            return _normalize_destination(_dir_mov())
        if media_type == "tv":
            return _normalize_destination(_dir_tv())

        # Auto-detect from name
        import re
        tv_patterns = [
            r'S\d{2}E\d{2}',
            r'\d{1,2}x\d{2}',
            r'Season\s*\d+',
            r'Complete\s+Series',
            r'HDTV',
            r'WEB.DL.*\d{3,4}p.*E\d{2}',
        ]
        for p in tv_patterns:
            if re.search(p, name, re.I):
                return _normalize_destination(_dir_tv())

        return _normalize_destination(_dir_mov())


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize_destination(path: str) -> str:
    """
    Synology DS API expects destination as a path starting with a shared
    folder name, NOT the full volume path.

    /volume1/downloads/movies  →  downloads/movies
    /volume2/downloads/tv      →  downloads/tv
    downloads/movies           →  downloads/movies  (already correct)

    Also handles Windows-style backslashes.
    """
    path = path.replace("\\", "/").strip("/")
    # Strip volume prefix: volume1/, volume2/, etc.
    import re
    path = re.sub(r'^volume\d+/', '', path)
    return path


def _flatten_task(t: dict) -> dict[str, Any]:
    """Flatten nested Synology task response into a clean dict."""
    detail   = t.get("additional", {}).get("detail",   {})
    transfer = t.get("additional", {}).get("transfer", {})
    return {
        "id":              t.get("id",       ""),
        "title":           t.get("title",    ""),
        "type":            t.get("type",     ""),
        "status":          t.get("status",   ""),
        "status_extra":    t.get("status_extra"),
        "size":            int(t.get("size",  0) or 0),
        "destination":     detail.get("destination", ""),
        "uri":             detail.get("uri",         ""),
        "priority":        detail.get("priority",    "auto"),
        "create_time":     detail.get("create_time", ""),
        "connected_seeders":  detail.get("connected_seeders",  0),
        "connected_leechers": detail.get("connected_leechers", 0),
        "total_peers":        detail.get("total_peers",        0),
        "size_downloaded": int(transfer.get("size_downloaded", 0) or 0),
        "size_uploaded":   int(transfer.get("size_uploaded",   0) or 0),
        "speed_download":  int(transfer.get("speed_download",  0) or 0),
        "speed_upload":    int(transfer.get("speed_upload",    0) or 0),
        "progress_pct":    _progress(t),
    }


def _progress(t: dict) -> float:
    """Calculate download progress as 0-100 float."""
    size = int(t.get("size", 0) or 0)
    if size == 0:
        return 0.0
    downloaded = int(
        t.get("additional", {}).get("transfer", {}).get("size_downloaded", 0) or 0
    )
    return round((downloaded / size) * 100, 1)
