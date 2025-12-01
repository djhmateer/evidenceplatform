# Archives Database Loader Guide

This document explains how the `archives_db_loader.py` script works and provides recommendations for running it in production on a remote VM.

---

## Overview

The Archives Database Loader (`extractors/archives_db_loader.py`) is the main ingestion pipeline for importing archived social media content (HAR files) into the database. It processes archive folders, extracts structured data, creates database records, and generates thumbnails.

### Command

```bash
poetry run python extractors/archives_db_loader.py 2>&1 | tee output.log
```

This runs the loader interactively, prompting for a stage to execute, with all output logged to `output.log`.

---

## Directory Structure

```
evidenceplatform/
├── archives/                          # Source archive folders
│   └── {archive_name}/                # e.g., eran_20250530_160037
│       ├── archive.har                # Main HAR file (HTTP Archive)
│       ├── metadata.json              # Archive metadata
│       ├── videos/                    # Extracted video files
│       │   └── *.mp4
│       └── photos/                    # Extracted image files
│           └── *.jpg
├── thumbnails/                        # Generated thumbnails
│   └── {md5_hash}.jpg
├── extractors/
│   ├── archives_db_loader.py          # Main loader script
│   ├── extract_videos.py              # Video extraction logic
│   ├── extract_photos.py              # Photo extraction logic
│   ├── db_intake.py                   # Database storage logic
│   ├── thumbnail_generator.py         # Thumbnail generation
│   └── structures_to_entities.py      # HAR → Entity conversion
└── browsing_platform/
    └── server/
        └── scripts/
            └── create_db.sql          # Database schema
```

---

## Processing Stages

When you run the script, you're prompted to select a stage:

```
Enter stage (register, parse, extract, full, thumbnails, add_attachments, clear_errors, add_metadata):
```

### Stage Descriptions

| Stage | Description | Idempotent | Safe to Re-run |
|-------|-------------|------------|----------------|
| `register` | Discovers archive folders and creates `archive_session` records | Yes | Yes |
| `parse` | Extracts structures from HAR files, stores as JSON | Yes | Yes (skips parsed) |
| `extract` | Creates `account`, `post`, `media` records from parsed structures | Yes | Yes (skips extracted) |
| `full` | Runs register → parse → extract → thumbnails | Yes | Yes |
| `thumbnails` | Generates missing thumbnails for media | Yes | Yes |
| `add_attachments` | Backfills missing `attachments` JSON field | Yes | Yes |
| `add_metadata` | Backfills missing `archiving_timestamp` | Yes | Yes |
| `clear_errors` | Resets `extraction_error` to NULL (allows reprocessing) | N/A | Yes |

---

## Detailed Stage Walkthrough

### 1. Register (`register_archives`)

**Purpose:** Make the database aware of archive folders.

**Process:**
1. Scans `archives/` directory for subdirectories
2. For each folder, checks if `archive_session` exists with matching `external_id`
3. If not, creates a new record:
   ```sql
   INSERT INTO archive_session (external_id, archive_location, source_type)
   VALUES ('har-{folder_name}', 'local_archive_har/{folder_name}', 1)
   ```

**Output Example:**
```
[LOADER] Scanning for archives in: /home/dave/code/evidenceplatform/archives
[LOADER] Found 1 archive directories
Registered archive eran_20250530_160037.
```

**What it creates:**
- One `archive_session` row per archive folder
- `source_type=1` indicates local HAR file

---

### 2. Parse (`parse_archives`)

**Purpose:** Extract structured data from HAR files without creating entity records.

**Process:**
1. Queries for unparsed sessions: `WHERE parsed_content IS NULL AND extraction_error IS NULL`
2. For each session:
   - Reads `metadata.json` for URL, timestamp, notes
   - Scans for attachments (screenshots, PDFs)
   - Parses `archive.har` using `extract_data_from_har()`
   - Extracts API responses (GraphQL, REST, HTML) containing account/post/media data
   - Scans for video segments embedded in HAR responses
   - Scans for photos embedded in HAR responses
3. Stores results:
   ```sql
   UPDATE archive_session SET
       parsed_content = 1,           -- parsing algorithm version
       structures = '{...}',         -- large JSON blob
       metadata = '{...}',
       attachments = '{...}',
       notes = '...'
   WHERE id = ?
   ```

**Important:** Parse does NOT download media or create entity records. Download options are disabled:
```python
VideoAcquisitionConfig(
    download_missing=False,
    download_media_not_in_structures=False,
    ...
)
```

**Output Example:**
```
[LOADER] Starting parse_archives...
[LOADER] Parsing archive: eran_20250530_160037 (session_id=1)
[LOADER] Archive directory: /home/dave/code/evidenceplatform/archives/eran_20250530_160037
[VIDEO] acquire_videos called: har_path=.../archive.har, output_dir=.../videos
[VIDEO] Found existing file: merged_1.mp4 (2456789 bytes)
...
[LOADER] Parsed all entries - no more unparsed archives.
```

---

### 3. Extract (`extract_entities`)

**Purpose:** Create actual database records from parsed structures.

**Process:**
1. Queries for parsed but not extracted sessions: `WHERE extracted_entities IS NULL AND parsed_content IS NOT NULL`
2. For each session:
   - Loads structures JSON from `archive_session.structures`
   - Converts to entities using `har_data_to_entities()`
   - For each entity type (accounts, posts, media):
     - Checks if entity exists (by URL or platform ID)
     - If exists: merges and updates
     - If new: inserts
     - Creates archive snapshot in `*_archive` table
3. Updates session:
   ```sql
   UPDATE archive_session SET extracted_entities = 1 WHERE external_id = ?
   ```

**What it creates:**
- `account` / `account_archive` records
- `post` / `post_archive` records
- `media` / `media_archive` records (with `local_url` paths)

**Output Example:**
```
[LOADER] Starting extract_entities...
[LOADER] Extracting entities for entry: har-eran_20250530_160037
[LOADER] Archive directory for extraction: /home/dave/code/evidenceplatform/archives/eran_20250530_160037
[DB] incorporate_structures_into_db called: archive_session_id=1, archive_location=...
[DB] Media local_url set to: local_archive_har/eran_20250530_160037/videos/merged_1.mp4
...
[LOADER] Extracted entities from all entries - no more to process.
```

---

### 4. Thumbnails (`generate_missing_thumbnails`)

**Purpose:** Generate thumbnail images for video and image media.

**Process:**
1. Queries for media without thumbnails: `WHERE thumbnail_path IS NULL AND local_url IS NOT NULL`
2. For each media:
   - Loads the file from `archives/{name}/videos/` or `archives/{name}/photos/`
   - For images: opens with PIL
   - For videos: extracts first frame with OpenCV
   - Resizes to 128x128
   - Saves to `thumbnails/{md5_hash}.jpg`
   - Updates database:
     ```sql
     UPDATE media SET thumbnail_path = 'local_thumbnails/{hash}.jpg' WHERE id = ?
     ```

**Output Example:**
```
Generating thumbnail for media ID 1 at /home/dave/code/evidenceplatform/archives/.../videos/merged_1.mp4
Generating thumbnail for media ID 2 at ...
```

---

### 5. Full (`full`)

Runs all stages in sequence:
```python
register_archives()
parse_archives()
extract_entities()
asyncio.run(generate_missing_thumbnails())
```

This is the recommended stage for initial imports and routine processing.

---

## Error Handling

### Extraction Errors

If any stage fails for a session, the error is stored:
```sql
UPDATE archive_session SET extraction_error = 'Error message...' WHERE id = ?
```

Sessions with errors are skipped in subsequent runs. Use `clear_errors` to reset and retry.

### Recovery Workflow

1. Check for errors:
   ```sql
   SELECT id, external_id, extraction_error FROM archive_session WHERE extraction_error IS NOT NULL;
   ```

2. Fix the underlying issue (missing files, malformed data, etc.)

3. Clear errors:
   ```bash
   poetry run python extractors/archives_db_loader.py
   # Enter: clear_errors
   ```

4. Re-run the failed stage:
   ```bash
   poetry run python extractors/archives_db_loader.py
   # Enter: parse  (or extract, depending on where it failed)
   ```

---

## File Path Aliasing

The system uses path aliases to decouple storage locations from database records:

| Alias | Actual Path | Used For |
|-------|-------------|----------|
| `local_archive_har` | `archives/` | Media files (videos, photos) |
| `local_thumbnails` | `thumbnails/` | Generated thumbnails |

The client rewrites these at runtime:
```typescript
// browsing_platform/client/src/services/server.tsx
if (path.startsWith("local_archive_har")) {
    path = path.replace("local_archive_har", "http://127.0.0.1:4444/archives");
}
```

---

## Production Deployment

### Prerequisites

1. **Python 3.12+** with Poetry
2. **MySQL 8.0+** database
3. **FFmpeg** and **ffprobe** (for video processing)
4. **System dependencies:**
   ```bash
   sudo apt-get install ffmpeg libgl1-mesa-glx libglib2.0-0
   ```

### Environment Setup

1. Clone the repository:
   ```bash
   git clone <repo-url> /opt/evidenceplatform
   cd /opt/evidenceplatform
   ```

2. Install dependencies:
   ```bash
   poetry install
   ```

3. Configure database connection (in `db.py` or via environment variables)

4. Initialize the database:
   ```bash
   mysql -u user -p < browsing_platform/server/scripts/create_db.sql
   ```

5. Create required directories:
   ```bash
   mkdir -p archives thumbnails
   ```

---

### Option 1: Manual Execution

Run the loader manually when new archives are added:

```bash
cd /opt/evidenceplatform
poetry run python extractors/archives_db_loader.py <<< "full" 2>&1 | tee -a /var/log/archives_loader.log
```

### Option 2: Cron Job

Schedule regular processing:

```bash
# /etc/cron.d/archives-loader
# Run every hour
0 * * * * appuser cd /opt/evidenceplatform && poetry run python extractors/archives_db_loader.py <<< "full" >> /var/log/archives_loader.log 2>&1
```

### Option 3: Systemd Service

Create a service for continuous processing:

```ini
# /etc/systemd/system/archives-loader.service
[Unit]
Description=Archives Database Loader
After=network.target mysql.service

[Service]
Type=oneshot
User=appuser
WorkingDirectory=/opt/evidenceplatform
ExecStart=/usr/bin/poetry run python extractors/archives_db_loader.py
StandardInput=file:/opt/evidenceplatform/stage_input.txt
StandardOutput=append:/var/log/archives_loader.log
StandardError=append:/var/log/archives_loader.log

[Install]
WantedBy=multi-user.target
```

Create input file:
```bash
echo "full" > /opt/evidenceplatform/stage_input.txt
```

Create a timer for periodic execution:
```ini
# /etc/systemd/system/archives-loader.timer
[Unit]
Description=Run Archives Loader hourly

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```

Enable:
```bash
sudo systemctl enable --now archives-loader.timer
```

### Option 4: Watch Directory with inotify

Process archives immediately when added:

```bash
#!/bin/bash
# /opt/evidenceplatform/watch_archives.sh

WATCH_DIR="/opt/evidenceplatform/archives"
LOG_FILE="/var/log/archives_loader.log"

inotifywait -m -e create -e moved_to --format '%w%f' "$WATCH_DIR" | while read NEWDIR
do
    if [ -d "$NEWDIR" ]; then
        echo "$(date): New archive detected: $NEWDIR" >> "$LOG_FILE"
        cd /opt/evidenceplatform
        poetry run python extractors/archives_db_loader.py <<< "full" >> "$LOG_FILE" 2>&1
    fi
done
```

Run as a systemd service:
```ini
# /etc/systemd/system/archives-watcher.service
[Unit]
Description=Watch for new archives
After=network.target

[Service]
Type=simple
User=appuser
ExecStart=/opt/evidenceplatform/watch_archives.sh
Restart=always

[Install]
WantedBy=multi-user.target
```

---

### Option 5: Non-Interactive Script Wrapper

Create a wrapper that doesn't require stdin:

```python
#!/usr/bin/env python3
# /opt/evidenceplatform/run_loader.py
"""
Non-interactive wrapper for archives_db_loader.py
Usage: poetry run python run_loader.py [stage]
Default stage: full
"""
import sys
import asyncio
sys.path.insert(0, '/opt/evidenceplatform')

from extractors.archives_db_loader import (
    register_archives, parse_archives, extract_entities,
    add_missing_attachments, add_missing_metadata, clear_extraction_errors
)
from extractors.thumbnail_generator import generate_missing_thumbnails

def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "full"

    print(f"[RUNNER] Starting stage: {stage}")

    if stage == "register":
        register_archives()
    elif stage == "parse":
        parse_archives()
    elif stage == "extract":
        extract_entities()
    elif stage == "full":
        register_archives()
        parse_archives()
        extract_entities()
        asyncio.run(generate_missing_thumbnails())
    elif stage == "thumbnails":
        asyncio.run(generate_missing_thumbnails())
    elif stage == "add_attachments":
        add_missing_attachments()
    elif stage == "add_metadata":
        add_missing_metadata()
    elif stage == "clear_errors":
        clear_extraction_errors()
    else:
        print(f"Unknown stage: {stage}")
        sys.exit(1)

    print(f"[RUNNER] Completed stage: {stage}")

if __name__ == "__main__":
    main()
```

Usage:
```bash
poetry run python run_loader.py full 2>&1 | tee -a /var/log/archives_loader.log
```

---

## Monitoring & Logging

### Log Rotation

```bash
# /etc/logrotate.d/archives-loader
/var/log/archives_loader.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 644 appuser appuser
}
```

### Health Check Query

```sql
-- Check processing status
SELECT
    COUNT(*) as total,
    SUM(CASE WHEN parsed_content IS NOT NULL THEN 1 ELSE 0 END) as parsed,
    SUM(CASE WHEN extracted_entities IS NOT NULL THEN 1 ELSE 0 END) as extracted,
    SUM(CASE WHEN extraction_error IS NOT NULL THEN 1 ELSE 0 END) as errors
FROM archive_session
WHERE source_type = 1;

-- Check recent errors
SELECT external_id, extraction_error, update_date
FROM archive_session
WHERE extraction_error IS NOT NULL
ORDER BY update_date DESC
LIMIT 10;

-- Check media without thumbnails
SELECT COUNT(*) FROM media WHERE thumbnail_path IS NULL AND local_url IS NOT NULL;
```

### Simple Monitoring Script

```bash
#!/bin/bash
# /opt/evidenceplatform/check_status.sh

echo "=== Archive Processing Status ==="
mysql -u user -p'password' evidenceplatform -e "
SELECT
    COUNT(*) as total,
    SUM(CASE WHEN parsed_content IS NOT NULL THEN 1 ELSE 0 END) as parsed,
    SUM(CASE WHEN extracted_entities IS NOT NULL THEN 1 ELSE 0 END) as extracted,
    SUM(CASE WHEN extraction_error IS NOT NULL THEN 1 ELSE 0 END) as errors
FROM archive_session WHERE source_type = 1;
"

echo ""
echo "=== Pending Thumbnails ==="
mysql -u user -p'password' evidenceplatform -e "
SELECT COUNT(*) as pending FROM media WHERE thumbnail_path IS NULL AND local_url IS NOT NULL;
"

echo ""
echo "=== Recent Errors ==="
mysql -u user -p'password' evidenceplatform -e "
SELECT external_id, LEFT(extraction_error, 50) as error FROM archive_session WHERE extraction_error IS NOT NULL LIMIT 5;
"
```

---

## Performance Considerations

### For Large Archives

1. **Disk Space:** HAR files can be large (100MB+). Ensure adequate storage.
2. **Memory:** Parsing large HAR files loads JSON into memory. Allow 2-4GB RAM.
3. **Database:** Add indexes as defined in `create_db.sql`.

### Parallel Processing

The current implementation processes one archive at a time. For parallel processing:

1. Run multiple instances with different archive folders
2. Or modify the code to use multiprocessing (requires careful database connection handling)

### Incremental Processing

All stages are idempotent and skip already-processed items:
- `register`: Skips existing `external_id`
- `parse`: Skips where `parsed_content IS NOT NULL`
- `extract`: Skips where `extracted_entities IS NOT NULL`
- `thumbnails`: Skips where `thumbnail_path IS NOT NULL`

This makes it safe to run `full` repeatedly.

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| "Video X not downloaded" | Media not in HAR or download disabled | Expected behavior during parse |
| "Post must have account_id" | Account not found for post | Check account extraction order |
| "Could not open video" | Corrupted or incomplete video file | Re-download or skip |
| "Metadata file not valid JSON" | Malformed metadata.json | Fix the JSON file |

### Debug Mode

Add verbose logging by modifying the print statements or setting:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Reset and Reprocess

To completely reprocess an archive:
```sql
-- Reset specific archive
UPDATE archive_session
SET parsed_content = NULL, extracted_entities = NULL, extraction_error = NULL
WHERE external_id = 'har-archive_name';

-- Delete associated records
DELETE FROM media_archive WHERE archive_session_id = ?;
DELETE FROM post_archive WHERE archive_session_id = ?;
DELETE FROM account_archive WHERE archive_session_id = ?;
```

Then run `full` again.

---

## Summary

| What | Command/Location |
|------|------------------|
| Run loader | `poetry run python extractors/archives_db_loader.py` |
| Full import | Enter `full` when prompted |
| Log output | `2>&1 \| tee output.log` |
| Archive location | `archives/{name}/` |
| Thumbnails location | `thumbnails/` |
| Database schema | `browsing_platform/server/scripts/create_db.sql` |
| Reset errors | Enter `clear_errors` then re-run stage |
