# Evidence Platform

## Development Setup

### Prerequisites
- Python with `uv` package manager
- Node.js with `pnpm` package manager
- MySQL database

### Environment Configuration

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

**Important:** Never commit your `.env` file to version control. It contains sensitive secrets.

### Loading Data

The loader expects data to be in the `archives` folder, organized in timestamped folders (e.g., `era_20250505_170837`) containing HAR files and other data files. 482GB currently on 20th Jan 26.

On 4th Feb I have extracted files from FTK

use (see in secrets directory)
```bash
rclone copy gdrive-personal: \
  --drive-root-folder-id foo-foo \
  /mnt/e/ftk \
  -P
```

Use Dbeaver or something to do a database dump just in case (on dev first)

To load new data into the database:
```bash
# this expects data to be in archives folder eg folders like eran_2025_1234
uv run db_loaders/archives_db_loader.py full

# to read from a separate drive - careful to have archives in the remote folder.
# took 6 hours to do the FTK run on dev
uv run db_loaders/archives_db_loader.py full --archives-dir /mnt/u/archives

# on prod takes 24mins with 32GB RAM
uv run db_loaders/archives_db_loader.py full --limit 100

# keep going if ssh disconnects
# took overnight to run on prod with 32GB RAM... maybe 14 hours.
nohup uv run db_loaders/archives_db_loader.py full &



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

---

## Production Deployment

### Backup Production Data

#### 1. Backup Database
```bash
# On production server
# 10mins
mysqldump -u golf -pSEESECRETSBUILDWEBSERVER evidenceplatform > evidenceplatform_backup_$(date +%Y%m%d_%H%M%S).sql
```

#### 2. Backup Files and Archives
```bash
# On production server
# Excludes SQL dumps from the archive backup and raw images

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

**Common mistake:** If you deployed and the frontend shows "Failed to fetch" or "ERR_CONNECTION_REFUSED", it means the frontend was built with the wrong API endpoint (likely `localhost:4444`). Rebuild with the correct production URL.

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
pnpm build

cd ../..
```

#### 3. Apply Database Migrations

TODO - make migrations

```bash
# If there are any schema changes, apply them here
# Example:
# mysql -u YOUR_DB_USER -pYOUR_DB_PASS evidenceplatform < migrations/001_add_new_table.sql
```

#### 4. Restart Services
```bash
# Stop the application (adjust based on your process manager)
# Example with systemd:
sudo systemctl stop evidenceplatform

# Or if using a process manager like PM2:
# pm2 stop evidenceplatform

# Restart the application
sudo systemctl start evidenceplatform
# Or: pm2 start evidenceplatform
```

## Security Notes

### Environment Files
- The `.env` file is automatically ignored by git (see `.gitignore`)
- Never commit secrets or credentials to version control
- Use different secrets for development, staging, and production
- Store production secrets in a secure vault system

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

