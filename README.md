# Evidence Platform

## Development Setup

### Prerequisites
- Python with `uv` package manager
- Node.js with `pnpm` package manager
- MySQL database

### Database Configuration
The database connection is configured in the `.env` file in the project root.

- Database Type: MySQL
- Database Name: `evidenceplatform`

Make sure your `.env` file contains the appropriate MySQL connection string.

### Loading Data

The loader expects data to be in the `archives` folder, organized in timestamped folders (e.g., `era_20250505_170837`) containing HAR files and other data files. 482GB currently on 20th Jan 26.

To load new data into the database:
```bash
uv run db_loaders/archives_db_loader.py full
```

This script processes archives in 4 stages:
- (A) Scans the `archives` folder and creates database records for any new archive folders not yet registered
- (B) Parses HAR files and metadata from unprocessed archives
- (C) Extracts entities (accounts, posts, media) into database tables
- (D) Generates thumbnails for media files

It's safe to run multiple times - it only processes new or unprocessed data.

Log files for the database loader are written to the `logs_db_loader` directory.

### Creating an Admin User

To create an admin user account:
```bash
uv run browsing_platform/server/scripts/add_user.py
```

The script will prompt you for an email and password (minimum 12 characters).

### Running in Development Mode

#### 1. Start the Python API Backend
From the project root:
```bash
uv sync --upgrade
BROWSING_PLATFORM_DEV=1 uv run python browse.py
```
This starts the API server on port **4444**.

#### 2. Start the React Frontend
In a separate terminal:
```bash
cd browsing_platform/client
pnpm update # TODO - there are dependency mismatches
pnpm start
```
This starts the React development server on port **3000**.

The frontend will be accessible at `http://localhost:3000` and will communicate with the API at `http://localhost:4444`.
