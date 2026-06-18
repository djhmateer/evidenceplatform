# Evidence Platform

**SEE ALSO create_webserver_exoscale.sh for good useful stuff**



## Development Setup

### Prerequisites
- Python with `uv` package manager
- Node.js with `pnpm` package manager
- MySQL database

### DEV Environment Configuration

The application requires a `.env` file in the project root. A sample configuration file is provided at `.env.sample`.

**First-time setup:**
1. Copy the sample environment file:
   ```bash
   cp .env.sample .env
   ```

2. Generate a secure file token secret:
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```
   Copy the output and set it as `FILE_TOKEN_SECRET` in your `.env` file.

3. Configure your MySQL database credentials in the `.env` file.


### Loading Data

The loader expects data to be in the `archives` folder, organized in timestamped folders (e.g., `era_20250505_170837`) containing HAR files and other data files. 482GB currently on 20th Jan 26.

We did use gdrive but not anymore as have a live file upload
use (see in secrets directory)
```bash
rclone copy gdrive-personal: \
  --drive-root-folder-id foo-foo \
  /mnt/e/ftk \
  -P
```

Use Dbeaver or something to do a database dump 

To load new data into the database:
```bash
# this expects data to be in archives folder eg folders like eran_2025_1234
# on prod 64GB of RAM was useful to go fast.. maybe 6 hours.
tmux
uv run db_loaders/archives_db_loader.py full

# to read from a separate drive - careful to have archives in the remote folder.
uv run db_loaders/archives_db_loader.py full --archives-dir /mnt/u/archives

# on prod takes 24mins with 32GB RAM
uv run db_loaders/archives_db_loader.py full --limit 100
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
BROWSING_PLATFORM_DEV=1 uv run python browsing_platform/server/server.py
```
This starts the API server on port **4444**.

#### 2. Start the React Frontend
In a separate terminal:
```bash
cd browsing_platform/client
pnpm update # TODO - there are dependency mismatches
pnpm start

# letmeinletmein is my dev password
```
This starts the React development server on port **3000**.

The frontend will be accessible at `http://localhost:3000` and will communicate with the API at `http://localhost:4444`.

#### Migrations

uv run infra/migrate.py

---

## Production Deployment

### Backup Production Data

#### 1. Backup Database
```bash
# On production server (see secrets create_webserver_exoscale.sh)
# 10mins
mysqldump --no-tablespaces -u golf -pSEESECRETSBUILDWEBSERVER evidenceplatform > evidenceplatform_backup_$(date +%Y%m%d_%H%M%S).sql
```

#### 2. Backup Files and Archives
```bash
# On production server
# Excludes SQL dumps from the archive backup

# only takes 5 mins or so
tar \
  --exclude='evidenceplatform.sql' \
  --exclude='__pycache__' \
  --exclude='*/__pycache__/*' \
  --exclude='archives' \
  --exclude='archives/*' \
  -cf - . \
| pv -s $(du -sb . | awk '{print $1}') \
| zstd -o backup.tar.zst
```


### Production Frontend Configuration

**IMPORTANT:** The frontend API endpoint is baked into the build at compile time.

**REQUIRED:** You must have a `.env.production` file in the `browsing_platform/client` directory before running `pnpm build`. Without this file, the build will use incorrect defaults.

Before building for production, configure the API endpoint:

```bash
cd browsing_platform/client
```

Edit `.env.production` to set your production domain:
```bash
REACT_APP_SERVER_ENDPOINT=https://your-production-domain.com/
GENERATE_SOURCEMAP=false
```

### Deploying Updates

#### 1. Pull Latest Code
```bash
git pull origin main
```

#### 2. Update Dependencies

**Backend:**
```bash
uv sync --upgrade
```

**Frontend:**
```bash
cd browsing_platform/client

# Install dependencies
pnpm install

# CRITICAL: Verify .env.production has the correct API endpoint
cat .env.production
# Should show: REACT_APP_SERVER_ENDPOINT=https://your-production-domain.com/

# Build for production (uses .env.production automatically)
# should put artifacts in the dist folder (build folder should be empty)
pnpm build

cd ../..
```


### Development Mode
When `BROWSING_PLATFORM_DEV=1` is set:
- ⚠️ **All authentication is bypassed**
- Use only for local development
- The application will refuse to start if dev mode is enabled with `ENVIRONMENT=production`

### File Token Security
The `FILE_TOKEN_SECRET` is used to encrypt file access tokens:
- Each token is cryptographically bound to a specific file path
- Tokens cannot be reused for different files
- Changing this secret will invalidate all existing file tokens
- Rotate this secret periodically as part of security best practices


## Prod DB

sudo mysql
use evidenceplatform
select * from users

## DEV

```bash
cd ~
mysqldump -u charlie -ppassword evidenceplatform > evidenceplatform_backup_$(date +%Y%m%d_%H%M%S).sql

uv run infra/migrate.py

# restore
mysql -u charlie -ppassword -e "DROP DATABASE evidenceplatform; CREATE DATABASE evidenceplatform;"
mysql -u charlie -ppassword evidenceplatform < evidenceplatform_backup_20260501_052942.sql
```

~/evidenceplatform/archives folder contains raw archives
 about 641GB 
  but now yaniv is uploading straight to the server

t:/ftk contains a backup from gdrive? 445GB

g:/   800GB - this is linked via fstab tab to archives folder
u:/archives2 - 208GB.. stuff that can't fit in above

have got a backup of prod archives on H:/evidence-platform
and db in t:/backups

 "toga>=0.5.3",  
removed from pyproject.toml
used in archiver/profile_selection.py - a gui for doing profiles

```bash
uv run infra/migrate.py --one-at-a-time
```

## Exoscale

see secrets/create_webserver_exoscale.sh

```bash
# dump prod on Azure
 mysqldump -u golf -ppassword5 evidenceplatform > evidenceplatform_backup_$(date +%Y%m%d_%H%M%S).sql

# copy prod to local filezilla
# zip?
#upload to Exoscale
unzip

tmux

git pull
uv sync --upgrade

# restore
mysql -u golf -ppassword5 -e "DROP DATABASE evidenceplatform; CREATE DATABASE evidenceplatform;"
# mysql -u golf -ppassword5 evidenceplatform < evidenceplatform_backup_20260501_052942.sql
mysql -u golf -ppassword5 evidenceplatform < evidenceplatform_backup_20260510_095026.sql

# run migrations
# started at 1238... finished at 1334
uv run infra/migrate.py

# backup db on exo
mysqldump --no-tablespaces -u golf -ppassword5 evidenceplatform > evidenceplatform_backup_$(date +%Y%m%d_%H%M%S).sql


mysql -u golf -ppassword5 evidenceplatform -e "UPDATE archive_session SET incorporation_status = 'pending'"

# test for dependencies
uv run db_loaders/archives_db_loader.py full --limit 1

sudo apt-get install libgl1 libglib2.0-0 -y

uv run db_loaders/archives_db_loader.py full

```
asdf

```sql
mysql -u golf -ppassword5

USE evidenceplatform;

-- had to do for migration 019
UPDATE post SET platform = 'instagram' WHERE platform IS NULL;
UPDATE post_archive SET platform = 'instagram' WHERE platform IS NULL;

-- useful for rerunning
UPDATE archive_session SET incorporation_status = 'pending' WHERE incorporation_status = 'parse_failed' OR incorporation_status = 'extract_failed' ;

```

## YANIV UPDATES

check local works
```bash
cd code/evidenceplatform
uv sync --upgrade
BROWSING_PLATFORM_DEV=1 uv run python browsing_platform/server/server.py
```
This starts the API server on port **4444**.

#### 2. Start the React Frontend
In a separate terminal:
```bash
cd browsing_platform/client
pnpm update # TODO - there are dependency mismatches
pnpm start

# davemateer@gmail.com
# letmeinletmein is my dev password
# 2FA is just the bottom one for evidenceplatform
```

merge in from his upstream

```bash
# 20GB
cd ~/code/
mysqldump -u charlie -ppassword evidenceplatform > evidenceplatform_backup_$(date +%Y%m%d_%H%M%S).sql

uv run infra/migrate.py

```

## PROD

```bash
mysqldump --no-tablespaces -u golf -ppassword5 evidenceplatform > evidenceplatform_backup_$(date +%Y%m%d_%H%M%S).sql
```
