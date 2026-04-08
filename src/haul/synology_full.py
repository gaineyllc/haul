"""
Full Synology Download Station API coverage.
Extends DownloadStation with all remaining API surfaces:
  - SYNO.DownloadStation.Statistic
  - SYNO.DownloadStation.Schedule
  - SYNO.DownloadStation.RSS.Site / RSS.Feed / RSS.Filter
  - SYNO.DownloadStation.BTSearch
  - Task priority + file selection + speed limits
"""
from __future__ import annotations
from typing import Any


class DownloadStationFull:
    """
    Mixin — attach to DownloadStation to get full API coverage.
    All methods assume self._sid, self._client, self.host, self._endpoint()
    are available (inherited from DownloadStation).
    """

    # ── Statistics ─────────────────────────────────────────────────────────────

    def get_statistics(self) -> dict[str, Any]:
        """
        Get global Download Station transfer statistics.
        Returns speed_download, speed_upload, error_download, error_upload.
        """
        r = self._client.get(
            f"{self.host}/webapi/DownloadStation/statistic.cgi",
            params={
                "api":     "SYNO.DownloadStation.Statistic",
                "version": "1",
                "method":  "getinfo",
                "_sid":    self._sid,
            },
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            return {}
        return {
            "speed_download":  data.get("data", {}).get("speed_download", 0),
            "speed_upload":    data.get("data", {}).get("speed_upload",   0),
            "error_download":  data.get("data", {}).get("error_download", 0),
            "error_upload":    data.get("data", {}).get("error_upload",   0),
        }

    # ── Priority & Speed ───────────────────────────────────────────────────────

    def set_task_priority(self, task_id: str,
                          priority: str = "normal") -> dict[str, Any]:
        """
        Set the priority for a download task.
        priority: 'auto' | 'low' | 'normal' | 'high'
        """
        if priority not in ("auto", "low", "normal", "high"):
            raise ValueError(f"Invalid priority: {priority!r}. Use auto/low/normal/high")
        r = self._client.get(
            self._endpoint(),
            params={
                "api":      self._api_name(),
                "version":  "2",
                "method":   "edit",
                "id":       task_id,
                "priority": priority,
                "_sid":     self._sid,
            },
        )
        r.raise_for_status()
        return r.json()

    def set_speed_limit(self, max_download_kb: int = 0,
                        max_upload_kb: int = 0) -> dict[str, Any]:
        """
        Set global speed limits in KB/s. 0 = unlimited.
        Uses SYNO.DownloadStation.Info setserverconfig.
        """
        r = self._client.get(
            f"{self.host}/webapi/DownloadStation/info.cgi",
            params={
                "api":              "SYNO.DownloadStation.Info",
                "version":          "1",
                "method":           "setserverconfig",
                "bt_max_download":  str(max_download_kb),
                "bt_max_upload":    str(max_upload_kb),
                "_sid":             self._sid,
            },
        )
        r.raise_for_status()
        return r.json()

    # ── File selection (multi-file torrents) ───────────────────────────────────

    def list_torrent_files(self, task_id: str) -> list[dict[str, Any]]:
        """
        List files inside a multi-file torrent task.
        Returns: [{index, filename, size, wanted, priority}]
        """
        r = self._client.get(
            self._endpoint(),
            params={
                "api":        self._api_name(),
                "version":    str(self._api_version),
                "method":     "getfiles",
                "id":         task_id,
                "additional": "wanted,priority",
                "_sid":       self._sid,
            },
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            return []
        files = data.get("data", {}).get("files", [])
        return [
            {
                "index":    i,
                "filename": f.get("filename", ""),
                "size":     int(f.get("size", 0) or 0),
                "wanted":   f.get("wanted", True),
                "priority": f.get("priority", "normal"),
            }
            for i, f in enumerate(files)
        ]

    def select_torrent_files(self, task_id: str,
                             wanted_indices: list[int]) -> dict[str, Any]:
        """
        Select which files to download from a multi-file torrent.
        wanted_indices: list of 0-based file indices to download.
        """
        r = self._client.get(
            self._endpoint(),
            params={
                "api":     self._api_name(),
                "version": str(self._api_version),
                "method":  "editfile",
                "id":      task_id,
                "wanted":  ",".join(str(i) for i in wanted_indices),
                "_sid":    self._sid,
            },
        )
        r.raise_for_status()
        return r.json()

    # ── Schedule ───────────────────────────────────────────────────────────────

    def get_schedule(self) -> dict[str, Any]:
        """
        Get the Download Station download schedule.
        Returns enabled flag and per-hour/day schedule matrix.
        """
        r = self._client.get(
            f"{self.host}/webapi/DownloadStation/schedule.cgi",
            params={
                "api":     "SYNO.DownloadStation.Schedule",
                "version": "1",
                "method":  "getconfig",
                "_sid":    self._sid,
            },
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            return {}
        cfg = data.get("data", {})
        return {
            "enabled": cfg.get("enabled", False),
            # schedule is a 7×24 matrix (days × hours), each cell is:
            # 0=no download, 1=download, 2=download+seeding
            "schedule": cfg.get("schedule", []),
        }

    def set_schedule(self, enabled: bool,
                     schedule: list[list[int]] | None = None) -> dict[str, Any]:
        """
        Set the download schedule.

        enabled: True to enforce schedule, False to always download
        schedule: 7×24 nested list (7 days, 24 hours each).
                  Each value: 0=disabled, 1=download, 2=download+seed
                  If None, uses all-enabled (download 24/7 when enabled=True)

        Example — only download 10pm-6am:
          schedule = [[2 if 22<=h or h<6 else 0 for h in range(24)] for _ in range(7)]
        """
        if schedule is None:
            # Default: all hours enabled
            schedule = [[1] * 24 for _ in range(7)]

        # Synology expects schedule as a flat string of 7*24=168 values
        flat = "".join(str(v) for row in schedule for v in row)

        r = self._client.get(
            f"{self.host}/webapi/DownloadStation/schedule.cgi",
            params={
                "api":      "SYNO.DownloadStation.Schedule",
                "version":  "1",
                "method":   "setconfig",
                "enabled":  str(enabled).lower(),
                "schedule": flat,
                "_sid":     self._sid,
            },
        )
        r.raise_for_status()
        return r.json()

    def set_schedule_hours(self, start_hour: int, end_hour: int,
                           days: list[int] | None = None) -> dict[str, Any]:
        """
        Convenience: set download to only happen between start_hour and end_hour.
        days: list of day indices 0-6 (0=Sun). None = all days.
        Hours are 24h format (0-23).

        Example: set_schedule_hours(22, 8) = download 10pm to 8am every day
        """
        if days is None:
            days = list(range(7))

        schedule = []
        for day in range(7):
            row = []
            for hour in range(24):
                if day in days:
                    if start_hour <= end_hour:
                        active = start_hour <= hour < end_hour
                    else:
                        # Wraps midnight: e.g. 22-8
                        active = hour >= start_hour or hour < end_hour
                    row.append(1 if active else 0)
                else:
                    row.append(0)
            schedule.append(row)

        return self.set_schedule(enabled=True, schedule=schedule)

    # ── RSS Feeds ──────────────────────────────────────────────────────────────

    def list_rss_sites(self) -> list[dict[str, Any]]:
        """List all configured RSS feed sites."""
        r = self._client.get(
            f"{self.host}/webapi/DownloadStation/RSS/site.cgi",
            params={
                "api":     "SYNO.DownloadStation.RSS.Site",
                "version": "1",
                "method":  "list",
                "_sid":    self._sid,
            },
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            return []
        return data.get("data", {}).get("sites", [])

    def add_rss_site(self, url: str) -> dict[str, Any]:
        """Add an RSS feed URL to Download Station."""
        r = self._client.get(
            f"{self.host}/webapi/DownloadStation/RSS/site.cgi",
            params={
                "api":     "SYNO.DownloadStation.RSS.Site",
                "version": "1",
                "method":  "create",
                "url":     url,
                "_sid":    self._sid,
            },
        )
        r.raise_for_status()
        return r.json()

    def delete_rss_site(self, site_id: str) -> dict[str, Any]:
        """Remove an RSS feed site."""
        r = self._client.get(
            f"{self.host}/webapi/DownloadStation/RSS/site.cgi",
            params={
                "api":     "SYNO.DownloadStation.RSS.Site",
                "version": "1",
                "method":  "delete",
                "id":      site_id,
                "_sid":    self._sid,
            },
        )
        r.raise_for_status()
        return r.json()

    def refresh_rss_site(self, site_id: str) -> dict[str, Any]:
        """Force-refresh an RSS feed."""
        r = self._client.get(
            f"{self.host}/webapi/DownloadStation/RSS/site.cgi",
            params={
                "api":     "SYNO.DownloadStation.RSS.Site",
                "version": "1",
                "method":  "refresh",
                "id":      site_id,
                "_sid":    self._sid,
            },
        )
        r.raise_for_status()
        return r.json()

    def list_rss_feeds(self, site_id: str) -> list[dict[str, Any]]:
        """List feed items from an RSS site."""
        r = self._client.get(
            f"{self.host}/webapi/DownloadStation/RSS/feed.cgi",
            params={
                "api":     "SYNO.DownloadStation.RSS.Feed",
                "version": "1",
                "method":  "list",
                "id":      site_id,
                "_sid":    self._sid,
            },
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            return []
        return data.get("data", {}).get("items", [])

    # ── RSS Filters (auto-download rules) ──────────────────────────────────────

    def list_rss_filters(self) -> list[dict[str, Any]]:
        """
        List all RSS auto-download filters.
        Each filter watches RSS feeds and auto-downloads matching items.
        """
        r = self._client.get(
            f"{self.host}/webapi/DownloadStation/RSS/filter.cgi",
            params={
                "api":     "SYNO.DownloadStation.RSS.Filter",
                "version": "1",
                "method":  "list",
                "_sid":    self._sid,
            },
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            return []
        return data.get("data", {}).get("filters", [])

    def add_rss_filter(
        self,
        name: str,
        feed_id: str,
        destination: str,
        match_pattern: str = "",
        exclude_pattern: str = "",
        use_regex: bool = False,
    ) -> dict[str, Any]:
        """
        Create an RSS auto-download filter.

        name:            Filter name
        feed_id:         RSS site/feed ID to watch
        destination:     Download destination (shared-folder-relative)
        match_pattern:   Keyword(s) to match — e.g. '2160p' or 'Severance'
        exclude_pattern: Keyword(s) to exclude — e.g. 'CAM TELESYNC'
        use_regex:       Treat patterns as regular expressions

        Example — auto-download 2160p Severance episodes:
          add_rss_filter(
              name='Severance 4K',
              feed_id='...',
              destination='downloads/tv',
              match_pattern='Severance.*2160p',
              exclude_pattern='CAM|TELESYNC',
              use_regex=True
          )
        """
        from src.haul.synology import _normalize_destination
        params = {
            "api":         "SYNO.DownloadStation.RSS.Filter",
            "version":     "1",
            "method":      "create",
            "name":        name,
            "feed_id":     feed_id,
            "destination": _normalize_destination(destination),
            "use_regex":   str(use_regex).lower(),
            "_sid":        self._sid,
        }
        if match_pattern:   params["match"]      = match_pattern
        if exclude_pattern: params["unmatch"]     = exclude_pattern

        r = self._client.get(
            f"{self.host}/webapi/DownloadStation/RSS/filter.cgi",
            params=params,
        )
        r.raise_for_status()
        return r.json()

    def delete_rss_filter(self, filter_id: str) -> dict[str, Any]:
        """Delete an RSS auto-download filter."""
        r = self._client.get(
            f"{self.host}/webapi/DownloadStation/RSS/filter.cgi",
            params={
                "api":     "SYNO.DownloadStation.RSS.Filter",
                "version": "1",
                "method":  "delete",
                "id":      filter_id,
                "_sid":    self._sid,
            },
        )
        r.raise_for_status()
        return r.json()

    # ── BT Search ─────────────────────────────────────────────────────────────

    def bt_search_start(self, keyword: str,
                        module: str = "enabled") -> dict[str, Any]:
        """
        Start a BitTorrent search across multiple trackers via DS.
        module: 'enabled' = all enabled search modules, or specific module name
        Returns task_id for polling results.
        """
        r = self._client.get(
            f"{self.host}/webapi/DownloadStation/btsearch.cgi",
            params={
                "api":     "SYNO.DownloadStation.BTSearch",
                "version": "1",
                "method":  "start",
                "keyword": keyword,
                "module":  module,
                "_sid":    self._sid,
            },
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            return {"error": str(data.get("error", {}))}
        return {"task_id": data.get("data", {}).get("taskid", ""), "keyword": keyword}

    def bt_search_results(self, task_id: str,
                          offset: int = 0,
                          limit: int = 50,
                          sort_by: str = "seeds",
                          order: str = "desc") -> dict[str, Any]:
        """
        Get results from a running BT search task.
        sort_by: 'name' | 'size' | 'date' | 'peers' | 'seeds' | 'leechs' | 'download'
        order:   'asc' | 'desc'
        """
        r = self._client.get(
            f"{self.host}/webapi/DownloadStation/btsearch.cgi",
            params={
                "api":     "SYNO.DownloadStation.BTSearch",
                "version": "1",
                "method":  "list",
                "taskid":  task_id,
                "offset":  str(offset),
                "limit":   str(limit),
                "sort_by": sort_by,
                "order":   order,
                "_sid":    self._sid,
            },
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            return {"status": "error", "items": []}
        d = data.get("data", {})
        return {
            "status":   d.get("status",    "searching"),
            "finished": d.get("finished",  False),
            "total":    d.get("total",     0),
            "items":    [
                {
                    "title":     item.get("title",    ""),
                    "size":      int(item.get("size",   0) or 0),
                    "seeds":     int(item.get("seeds",  0) or 0),
                    "leechers":  int(item.get("leechs", 0) or 0),
                    "download_uri": item.get("download_uri", ""),
                    "source":    item.get("source",   ""),
                    "date":      item.get("date",     ""),
                }
                for item in d.get("items", [])
            ],
        }

    def bt_search_stop(self, task_id: str) -> dict[str, Any]:
        """Stop a running BT search."""
        r = self._client.get(
            f"{self.host}/webapi/DownloadStation/btsearch.cgi",
            params={
                "api":    "SYNO.DownloadStation.BTSearch",
                "version":"1",
                "method": "stop",
                "taskid": task_id,
                "_sid":   self._sid,
            },
        )
        r.raise_for_status()
        return r.json()

    def bt_search_modules(self) -> list[dict[str, Any]]:
        """List available BT search modules/trackers."""
        r = self._client.get(
            f"{self.host}/webapi/DownloadStation/btsearch.cgi",
            params={
                "api":     "SYNO.DownloadStation.BTSearch",
                "version": "1",
                "method":  "getmodules",
                "_sid":    self._sid,
            },
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            return []
        return data.get("data", {}).get("modules", [])
