# Browsing Platform Architecture

## Overview

The Browsing Platform is an **evidence archival and analysis system** designed to capture, preserve, and analyze social media content from various platforms. It provides a web-based interface for browsing archived content, with a focus on maintaining provenance and historical accuracy.

### Technology Stack

- **Client**: React/TypeScript with Vite, started via `pnpm dev` in `browsing_platform/client/`
- **Server**: Python with Flask, started via `poetry run python browse.py` from the repository root
- **Database**: MySQL with raw SQL queries (no ORM)
- **Data Validation**: Pydantic models for entity validation and serialization

---

## Core Architecture Concepts

### Dual-Table Architecture

The system uses a **dual-table architecture** where each core entity type has two corresponding tables:

1. **Main Tables** - Store the canonical/current version of each entity
2. **Archive Tables** - Store immutable historical snapshots tied to specific archival sessions

This design enables:
- **Provenance tracking**: Know exactly which archive session each piece of data came from
- **Historical preservation**: See how content appeared at the moment it was archived
- **Canonical deduplication**: Multiple archives of the same content link to a single canonical record
- **Temporal analysis**: Compare how content changes over time across different archival sessions

### Entity Identification

Entities are identified through multiple mechanisms:
- **Internal ID** (`id`): Auto-increment primary key for internal references
- **Platform ID** (`id_on_platform`): The ID assigned by the source platform (Instagram, TikTok, etc.)
- **URL** (`url`): The canonical URL of the entity, normalized (query params removed, trailing slashes stripped)

When ingesting data, the system first attempts to match existing entities by URL, then by platform ID.

---

## Database Schema

### Schema Location

The database schema is defined in: `browsing_platform/server/scripts/create_db.sql`

### Table Overview

| Category | Tables |
|----------|--------|
| **Core Entities** | `account`, `post`, `media`, `post_engagement`, `account_relation` |
| **Archive Snapshots** | `account_archive`, `post_archive`, `media_archive`, `post_engagement_archive`, `account_relation_archive` |
| **Archival Management** | `archive_session` |
| **Tagging System** | `tag`, `tag_type`, `tag_hierarchy`, `account_tag`, `post_tag`, `media_tag`, `media_part_tag`, `post_engagement_tag` |
| **Media Segments** | `media_part` |
| **Authentication** | `user`, `token` |
| **System** | `error_log` |

---

## Core Entities

### Archive Session (`archive_session`)

The **central hub** for all archived data. An archive session represents a single archival capture event from a specific source.

```sql
CREATE TABLE archive_session (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    create_date         TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_date         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Identification
    external_id         VARCHAR(60) NULL,      -- External reference ID
    archived_url        VARCHAR(200) NULL,     -- The URL that was archived
    archive_location    VARCHAR(200) NULL,     -- Where archive files are stored locally

    -- Content
    summary_html        LONGTEXT NULL,         -- HTML summary of archived content
    structures          JSON NULL,             -- Extracted entity structure (hierarchical)
    metadata            JSON NULL,             -- Archive metadata from source
    attachments         JSON NULL,             -- File attachment information

    -- Processing State
    parsed_content      INT NULL,              -- Version of parsing code used
    extracted_entities  INT NULL,              -- Count of entities extracted
    extraction_error    VARCHAR(500) NULL,     -- Error message if extraction failed

    -- Source Information
    source_type         INT DEFAULT 0 NOT NULL,-- 0=AA_xlsx, 1=local_hars, 2=local_wacz
    archiving_timestamp DATETIME NULL,         -- When the original archiving occurred

    -- User Data
    notes               TEXT NULL,             -- User annotations
    archived_url_parts  TEXT NULL              -- URL parts for full-text search
);
```

**Source Types:**
| Value | Source | Description |
|-------|--------|-------------|
| 0 | AA_xlsx | Archive Angel XLSX export files |
| 1 | local_hars | Local HAR (HTTP Archive) files |
| 2 | local_wacz | Local WACZ (Web Archive Collection Zipped) files |

**Key Fields Explained:**
- `parsed_content`: Tracks which version of the parsing/extraction code was used. Allows reprocessing older records when parsing logic improves.
- `structures`: JSON containing the hierarchical structure of extracted entities (posts containing media, accounts with followers, etc.)
- `extraction_error`: Populated when entity extraction fails, enabling error tracking and retry logic.

---

### Account (`account` / `account_archive`)

Represents a social media profile/user account.

#### Main Table: `account`
```sql
CREATE TABLE account (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    create_date    TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_date    TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Identification
    id_on_platform VARCHAR(100) NULL,          -- Platform's user ID
    url            VARCHAR(200) NOT NULL,      -- Profile URL (canonical identifier)

    -- Profile Data
    display_name   VARCHAR(100) NULL,          -- Display name / username
    bio            VARCHAR(200) NULL,          -- Biography / description
    data           JSON NULL,                  -- Platform-specific metadata

    -- User Annotations
    notes          TEXT NULL,                  -- User-added notes
    url_parts      TEXT NULL                   -- URL parts for full-text search
);
```

#### Archive Table: `account_archive`
```sql
CREATE TABLE account_archive (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    create_date        TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_date        TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Archive Linking
    canonical_id       INT NULL,               -- Links to account.id
    archive_session_id INT NULL,               -- Links to archive_session.id

    -- Identification (same as main table)
    id_on_platform     VARCHAR(100) NULL,
    url                VARCHAR(200) NOT NULL,

    -- Profile Data (snapshot at archive time)
    display_name       VARCHAR(100) NULL,
    bio                VARCHAR(200) NULL,
    data               JSON NULL

    -- NOTE: No 'notes' field - archive records are immutable
);
```

**Differences Between Main and Archive:**
| Field | Main Table | Archive Table |
|-------|------------|---------------|
| `canonical_id` | Not present | Links to main table record |
| `archive_session_id` | Not present | Links to archive session |
| `notes` | Present (user editable) | Not present (immutable) |
| `url_parts` | Present (for search) | Not present |

---

### Post (`post` / `post_archive`)

Represents a social media post (tweet, Instagram post, TikTok video, etc.).

#### Main Table: `post`
```sql
CREATE TABLE post (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    create_date      TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_date      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Identification
    id_on_platform   VARCHAR(100) NULL,        -- Platform's post ID
    url              VARCHAR(250) NOT NULL,    -- Post URL

    -- Relationships
    account_id       INT NULL,                 -- FK to account (author)

    -- Content
    publication_date DATETIME NULL,            -- When post was published
    caption          TEXT NULL,                -- Post text / caption
    data             JSON NULL,                -- Platform-specific metadata

    -- User Annotations
    notes            TEXT NULL
);
```

#### Archive Table: `post_archive`
```sql
CREATE TABLE post_archive (
    id                     INT AUTO_INCREMENT PRIMARY KEY,
    create_date            TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_date            TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Archive Linking
    canonical_id           INT NULL,           -- Links to post.id
    archive_session_id     INT NULL,           -- Links to archive_session.id

    -- Identification
    id_on_platform         VARCHAR(100) NULL,
    url                    VARCHAR(250) NOT NULL,

    -- Relationships (DENORMALIZED)
    account_url            VARCHAR(200) NULL,  -- Author's profile URL
    account_id_on_platform VARCHAR(100) NULL,  -- Author's platform ID

    -- Content
    publication_date       DATETIME NULL,
    caption                TEXT NULL,
    data                   JSON NULL
);
```

**Note on Denormalization:**
Archive tables use denormalized references (URLs and platform IDs) instead of foreign keys. This ensures archive records remain self-contained and queryable even if the main table records are modified or deleted.

---

### Media (`media` / `media_archive`)

Represents media attachments (images, videos, audio) associated with posts.

#### Main Table: `media`
```sql
CREATE TABLE media (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    create_date    TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_date    TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Identification
    id_on_platform VARCHAR(100) NULL,          -- Platform's media ID
    url            VARCHAR(250) NOT NULL,      -- Original media URL

    -- Relationships
    post_id        INT NULL,                   -- FK to post

    -- Local Storage
    local_url      VARCHAR(500) NULL,          -- Local file path (downloaded)
    thumbnail_path VARCHAR(200) NULL,          -- Generated thumbnail path

    -- Content Metadata
    media_type     ENUM('video', 'audio', 'image') NOT NULL,
    data           JSON NULL,                  -- Platform-specific metadata

    -- Annotations
    annotation     TEXT NULL,                  -- Content description
    notes          TEXT NULL                   -- User notes
);
```

#### Archive Table: `media_archive`
```sql
CREATE TABLE media_archive (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    create_date         TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_date         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Archive Linking
    canonical_id        INT NULL,              -- Links to media.id
    archive_session_id  INT NULL,              -- Links to archive_session.id

    -- Identification
    id_on_platform      VARCHAR(100) NULL,
    url                 VARCHAR(250) NOT NULL,

    -- Relationships (DENORMALIZED)
    post_url            VARCHAR(250) NULL,     -- Parent post URL
    post_id_on_platform VARCHAR(100) NULL,     -- Parent post platform ID

    -- Local Storage
    local_url           VARCHAR(500) NULL,

    -- Content Metadata
    media_type          ENUM('video', 'audio', 'image') NOT NULL,
    data                JSON NULL

    -- NOTE: No annotation, thumbnail_path, or notes (archive is raw snapshot)
);
```

---

### Post Engagement (`post_engagement` / `post_engagement_archive`)

Represents engagement actions on posts (likes, comments, shares, etc.).

#### Main Table: `post_engagement`
```sql
CREATE TABLE post_engagement (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    create_date    TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_date    TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Identification
    id_on_platform VARCHAR(100) NULL,          -- Platform's engagement ID
    url            VARCHAR(250) NOT NULL,      -- Engagement URL (if applicable)

    -- Relationships
    post_id        INT NULL,                   -- FK to post being engaged with
    account_id     INT NULL,                   -- FK to account doing the engaging

    -- User Annotations
    notes          TEXT NULL
);
```

#### Archive Table: `post_engagement_archive`
```sql
CREATE TABLE post_engagement_archive (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    create_date         TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_date         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Archive Linking
    canonical_id        INT NULL,              -- Links to post_engagement.id
    archive_session_id  INT NULL,              -- Links to archive_session.id

    -- Identification
    id_on_platform      VARCHAR(100) NULL,
    url                 VARCHAR(250) NOT NULL,

    -- Relationships (DENORMALIZED)
    post_url            VARCHAR(250) NULL,
    post_id_on_platform VARCHAR(100) NULL,

    -- Content
    engagement_date     DATETIME NULL,         -- When engagement occurred
    caption             TEXT NULL,             -- Comment text (if applicable)
    data                JSON NULL
);
```

---

### Account Relation (`account_relation` / `account_relation_archive`)

Represents relationships between accounts (following, followers, etc.).

#### Main Table: `account_relation`
```sql
CREATE TABLE account_relation (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    create_date         TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_date         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Relationships
    followed_account_id INT NOT NULL,          -- FK to account being followed
    follower_account_id INT NOT NULL,          -- FK to account doing the following

    -- Metadata
    relation_type       VARCHAR(30) NULL,      -- Type: 'following', 'follower', etc.
    notes               TEXT NULL
);
```

#### Archive Table: `account_relation_archive`
```sql
CREATE TABLE account_relation_archive (
    id                              INT AUTO_INCREMENT PRIMARY KEY,
    create_date                     TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_date                     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Archive Linking
    canonical_id                    INT NULL,
    archive_session_id              INT NULL,

    -- Identification
    id_on_platform                  VARCHAR(100) NULL,

    -- Relationships (DENORMALIZED)
    followed_account_url            VARCHAR(200) NOT NULL,
    followed_account_id_on_platform VARCHAR(100) NULL,
    follower_account_url            VARCHAR(200) NOT NULL,
    follower_account_id_on_platform VARCHAR(100) NULL,

    -- Metadata
    relation_type                   VARCHAR(30) NULL,
    data                            JSON NULL
);
```

---

## Entity Relationships Diagram

```
                         ┌─────────────────────┐
                         │   archive_session   │
                         │                     │
                         │ - external_id       │
                         │ - archived_url      │
                         │ - source_type       │
                         │ - structures (JSON) │
                         └──────────┬──────────┘
                                    │
                                    │ archive_session_id
          ┌─────────────────────────┼─────────────────────────┐
          │                         │                         │
          ▼                         ▼                         ▼
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│ account_archive │      │  post_archive   │      │ media_archive   │
│                 │      │                 │      │                 │
│ canonical_id ───┼──┐   │ canonical_id ───┼──┐   │ canonical_id ───┼──┐
└─────────────────┘  │   └─────────────────┘  │   └─────────────────┘  │
                     │                        │                        │
                     ▼                        ▼                        ▼
              ┌─────────────┐          ┌─────────────┐          ┌─────────────┐
              │   account   │◄─────────│    post     │◄─────────│    media    │
              │             │          │             │          │             │
              │ - url       │ account_ │ - url       │  post_   │ - url       │
              │ - display   │    id    │ - caption   │    id    │ - media_type│
              │ - bio       │          │ - pub_date  │          │ - local_url │
              └──────┬──────┘          └─────────────┘          └─────────────┘
                     │
                     │ followed_account_id
                     │ follower_account_id
                     ▼
              ┌─────────────────┐
              │ account_relation│
              │                 │
              │ - relation_type │
              └─────────────────┘
```

---

## Tagging System

The platform includes a flexible tagging system that allows users to annotate any entity type.

### Tag Definition Tables

#### `tag`
```sql
CREATE TABLE tag (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    create_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    name        VARCHAR(200) NOT NULL,
    description TEXT NULL,
    tag_type_id INT NULL,                      -- FK to tag_type

    CONSTRAINT UNIQUE (name, tag_type_id)      -- Tags unique within type
);
```

#### `tag_type`
```sql
CREATE TABLE tag_type (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    create_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    name        VARCHAR(200) NOT NULL,
    description TEXT NULL,
    notes       TEXT NULL
);
```

#### `tag_hierarchy`
Enables parent-child relationships between tags.
```sql
CREATE TABLE tag_hierarchy (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    create_date         TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_date         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    super_tag_id        INT NOT NULL,          -- Parent tag
    sub_tag_id          INT NOT NULL,          -- Child tag
    temporal_constraint VARCHAR(100) NULL,     -- Time-based constraint
    notes               TEXT NULL,

    CONSTRAINT UNIQUE (super_tag_id, sub_tag_id)
);
```

### Entity-Tag Junction Tables

Each entity type has a corresponding junction table for many-to-many tag relationships:

| Junction Table | Links |
|----------------|-------|
| `account_tag` | `account` ↔ `tag` |
| `post_tag` | `post` ↔ `tag` |
| `media_tag` | `media` ↔ `tag` |
| `media_part_tag` | `media_part` ↔ `tag` |
| `post_engagement_tag` | `post_engagement` ↔ `tag` |

Each junction table has the same structure:
```sql
CREATE TABLE {entity}_tag (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    create_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    {entity}_id INT NOT NULL,
    tag_id      INT NOT NULL,
    notes       TEXT NULL,

    CONSTRAINT UNIQUE ({entity}_id, tag_id)
);
```

### Tagging Diagram

```
┌─────────┐     ┌─────────────┐     ┌──────────────┐
│   tag   │◄────┤ account_tag │────►│   account    │
│         │     └─────────────┘     └──────────────┘
│ - name  │     ┌─────────────┐     ┌──────────────┐
│ - type  │◄────┤  post_tag   │────►│    post      │
│         │     └─────────────┘     └──────────────┘
│         │     ┌─────────────┐     ┌──────────────┐
│         │◄────┤  media_tag  │────►│    media     │
└────┬────┘     └─────────────┘     └──────────────┘
     │
     ▼
┌───────────────┐
│ tag_hierarchy │
│               │
│ super ──► sub │
└───────────────┘
```

---

## Media Parts (`media_part`)

Allows referencing specific portions of media files for detailed annotation.

```sql
CREATE TABLE media_part (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    create_date           TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_date           TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Relationship
    media_id              INT NOT NULL,        -- FK to media

    -- Spatial Selection (for images/video frames)
    crop_area             VARCHAR(100) NULL,   -- Crop coordinates

    -- Temporal Selection (for video/audio)
    timestamp_range_start FLOAT NULL,          -- Start time in seconds
    timestamp_range_end   FLOAT NULL,          -- End time in seconds

    -- Annotations
    notes                 TEXT NULL
);
```

**Use Cases:**
- Highlighting a specific region of an image
- Clipping a specific segment of a video
- Annotating a particular moment in audio

---

## Authentication System

### User (`user`)
```sql
CREATE TABLE user (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    create_date      DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_date      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Identity
    email            VARCHAR(200) NOT NULL UNIQUE,

    -- Authentication
    password_hash    VARCHAR(255) NULL,
    password_alg     VARCHAR(20) NULL,         -- Hashing algorithm used
    password_set_at  DATETIME NULL,

    -- Security State
    locked           TINYINT DEFAULT 0 NOT NULL,
    force_pwd_reset  TINYINT DEFAULT 0 NOT NULL,
    login_attempts   INT DEFAULT 0 NOT NULL,
    last_pwd_failure DATETIME NULL,
    last_login       DATETIME NULL,

    -- Authorization
    admin            TINYINT DEFAULT 0 NOT NULL
);
```

### Token (`token`)
```sql
CREATE TABLE token (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    create_date DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    last_use    DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    token       VARCHAR(100) NOT NULL UNIQUE,

    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
);
```

**Note:** The `ON DELETE CASCADE` ensures tokens are automatically deleted when their associated user is deleted.

---

## Error Logging (`error_log`)

```sql
CREATE TABLE error_log (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    timestamp  TIMESTAMP DEFAULT CURRENT_TIMESTAMP NULL,
    event_type ENUM(
        'server_call',
        'sql_error',
        'unknown_error',
        'unauthorized_access',
        'login_attempt'
    ) NOT NULL,
    user_id    INT NULL,
    details    TEXT NULL,
    args       TEXT NULL
);
```

---

## Data Flow

### Archiving Process

```
┌─────────────────────────────────────────────────────────────────┐
│                     1. ARCHIVE SOURCE                           │
│                                                                 │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐                │
│   │ AA XLSX  │    │ HAR File │    │ WACZ File│                │
│   │ (type=0) │    │ (type=1) │    │ (type=2) │                │
│   └────┬─────┘    └────┬─────┘    └────┬─────┘                │
│        └───────────────┼───────────────┘                       │
└────────────────────────┼───────────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              2. CREATE ARCHIVE SESSION                          │
│                                                                 │
│   INSERT INTO archive_session (                                 │
│       archived_url, archive_location, source_type, ...         │
│   )                                                             │
└────────────────────────┼───────────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              3. EXTRACT ENTITIES                                │
│                                                                 │
│   Parse archive content → Extract accounts, posts, media        │
│   Store in archive_session.structures (JSON)                    │
└────────────────────────┼───────────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              4. FOR EACH ENTITY                                 │
│                                                                 │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │ a) Check if entity exists in main table                 │  │
│   │    - Match by URL first                                 │  │
│   │    - Match by id_on_platform second                     │  │
│   └───────────────────────┬─────────────────────────────────┘  │
│                           ▼                                     │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │ b) If EXISTS: Merge and update main table               │  │
│   │    If NEW: Insert into main table                       │  │
│   │    → Get canonical_id (main table ID)                   │  │
│   └───────────────────────┬─────────────────────────────────┘  │
│                           ▼                                     │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │ c) Create archive snapshot                              │  │
│   │    - Set canonical_id = main table ID                   │  │
│   │    - Set archive_session_id = current session           │  │
│   │    - Insert into {entity}_archive table                 │  │
│   └─────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Query Patterns

**Get canonical entity with all archive snapshots:**
```sql
SELECT
    a.*,
    aa.archive_session_id,
    aa.display_name as archived_display_name,
    aa.bio as archived_bio,
    s.archiving_timestamp
FROM account a
LEFT JOIN account_archive aa ON aa.canonical_id = a.id
LEFT JOIN archive_session s ON s.id = aa.archive_session_id
WHERE a.id = ?
ORDER BY s.archiving_timestamp;
```

**Get all entities from a specific archive session:**
```sql
SELECT * FROM account_archive WHERE archive_session_id = ?;
SELECT * FROM post_archive WHERE archive_session_id = ?;
SELECT * FROM media_archive WHERE archive_session_id = ?;
```

---

## Key Files

| Component | Location |
|-----------|----------|
| SQL Schema | `browsing_platform/server/scripts/create_db.sql` |
| Python Entity Models | `extractors/entity_types.py` |
| Database Connection | `db.py` |
| Data Intake Logic | `extractors/db_intake.py` |
| Server Entry Point | `browse.py` |
| Client Entry Point | `browsing_platform/client/` (Vite/React) |
| Server Services | `browsing_platform/server/services/` |

---

## Design Principles

### 1. Immutable Archive Records
Archive tables never have `notes` fields. Once created, archive records represent an immutable snapshot of what the data looked like at archival time.

### 2. Denormalized References in Archives
Archive tables store URLs and platform IDs instead of foreign key references. This ensures:
- Archive records remain meaningful even if main table records are deleted
- Archives are self-contained and can be exported independently
- No cascading issues with foreign key constraints

### 3. Version Tracking for Reprocessing
The `parsed_content` field in `archive_session` tracks which version of the parsing code was used. This enables:
- Identifying records processed with outdated logic
- Selective reprocessing when extraction algorithms improve
- Audit trail of processing history

### 4. Flexible JSON Storage
Platform-specific metadata is stored in `data` JSON fields, allowing:
- Storage of arbitrary platform-specific fields
- Schema evolution without migrations
- Easy addition of new platform support

### 5. Full-Text Search
Strategic full-text indexes enable efficient searching across:
- Account URLs, display names, bios
- Post captions and URLs
- Archive session URLs
- User annotations (notes)

---

## Future Considerations (TODOs in Schema)

1. **Character Set Migration**: Move from `utf8mb3` to `utf8mb4` for full Unicode support
2. **Foreign Key Constraints**: Add explicit FK constraints for `post.account_id`, `media.post_id`, etc.
3. **Datetime Consistency**: Standardize UTC handling across all timestamp fields
4. **ID Field Types**: Consider unsigned integers and timestamps beyond 2038
