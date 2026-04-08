# Download Station Tool Reference

## Task management

```python
haul_list_downloads()
# Returns: [{id, title, status, progress_pct, speed_download, destination, ...}]

haul_get_task(task_id)
haul_pause_task(task_id)
haul_resume_task(task_id)
haul_delete_task(task_id, force_complete=False)
haul_edit_destination(task_id, destination)
haul_set_priority(task_id, priority)  # auto|low|normal|high
```

## Speed & stats

```python
haul_set_speed_limit(max_download_kb=0, max_upload_kb=0)  # 0=unlimited
haul_get_stats()  # global speeds + error counts
```

## Multi-file torrents

```python
files = haul_list_torrent_files(task_id)
# → [{index, filename, size, wanted, priority}]

haul_select_files(task_id, wanted_indices=[0, 2, 3])
# Downloads only files at those indices
```

## Schedule

```python
haul_get_schedule()
haul_set_schedule_hours(22, 8)       # 10pm–8am every day
haul_set_schedule_hours(1, 6, [1,2,3,4,5])  # 1–6am weekdays
haul_disable_schedule()              # always on
```

## RSS feeds

```python
# Discovery
sites = haul_list_rss_sites()
feeds = haul_list_rss_feeds(site_id)

# Management
haul_add_rss_site(url)
haul_delete_rss_site(site_id)
haul_refresh_rss_site(site_id)
```

## RSS auto-download filters

```python
# List existing
haul_list_rss_filters()

# Create: auto-download 2160p Severance episodes
haul_add_rss_filter(
    name="Severance 4K",
    feed_id="site123",
    destination="downloads/tv",
    match_pattern="Severance.*2160p",
    exclude_pattern="CAM|TELESYNC",
    use_regex=True
)

haul_delete_rss_filter(filter_id)
```

## BT search (DS built-in tracker search)

```python
# Start search
r = haul_bt_search("The Boys S05E01")
task_id = r["task_id"]

# Poll until finished=True
while True:
    results = haul_bt_search_results(task_id, sort_by="seeds")
    if results["finished"]: break

# Add best result to DS
haul_bt_add_result(results["items"][0]["download_uri"], "downloads/tv")

# List available search modules
haul_bt_search_modules()
```

## NAS folders

```python
haul_list_folders()
# → [{name, path, is_writable}]
# Use to discover valid destination paths
```
