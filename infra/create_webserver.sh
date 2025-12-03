#!/bin/sh

# disable auto upgrades by apt - in dev mode only
cd /home/dave

# go with newer apt which gets dependency updates too (like linux-azure)
sudo apt-get update -y
sudo apt-get upgrade -y

sudo apt-get install unzip -y

# /home/dave/server
# /home/dave/client
# o for overwrite
# q for quiet
unzip -oq all.zip



## FRONTEND Client 

# need node installed to do a build

# nvm
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion


# node 24.11.1 and npm 11.6.2 on 26th Nov 25
nvm install --lts --latest-npm

npm install --global corepack@latest

# pnpm
corepack enable pnpm
corepack prepare pnpm@latest --activate

cd /home/dave/browsing_platform/client

pnpm install --frozen-lockfile

pnpm update

# creates static files in /home/dave/browsing_platform/client/dist
# using the older webpack (slower) build - vite would be faster.

# need this so that the correct endpoint is baked into the build
# note this is a single line command. use export REACT_APP_SERVER_ENDPOINT=https://evidenceplatform.org/ if want mulitple
REACT_APP_SERVER_ENDPOINT=https://evidenceplatform.org/ \
pnpm build


## BACKEND Server
cd /home/dave

# install uv (universal venv) 
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env 

uv lock --upgrade
uv sync

## MySQL

sudo apt-get install mysql-server -y

# exit 0

# create database and user and tables and sample data
# run the file create_db.sql    
sudo mysql < /home/dave/infra/create_db.sql

sudo mysql < /home/dave/secrets/insert_data.sql


## Run FastAPI server under uv as a systemd service 

cd /home/dave
mkdir archives
mkdir thumbnails

# Set up systemd service for the API
sudo tee /etc/systemd/system/evidenceplatform.service > /dev/null <<EOF
[Unit]
Description=Evidence Platform API
After=network.target mysql.service

[Service]
Type=simple
User=dave
WorkingDirectory=/home/dave
Environment=ENVIRONMENT=production
Environment=DB_USER=golf
Environment=DB_PASS=password5
Environment=DB_NAME=evidenceplatform
Environment=DB_PORT=3306
Environment=DB_HOST=localhost
Environment=DEFAULT_SIGNATURE=your_prod_signature
Environment=BROWSING_PLATFORM_DEV=0

ExecStart=/home/dave/.local/bin/uv run python browse.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable evidenceplatform
sudo systemctl start evidenceplatform

# this is handy to test manually 
# ENVIRONMENT=production \
# DB_USER=golf \
# DB_PASS=password5 \
# DB_NAME=evidenceplatform \
# DB_PORT=3306 \
# DB_HOST=localhost \
# DEFAULT_SIGNATURE=your_prod_signature \
# BROWSING_PLATFORM_DEV=0 \
# /home/dave/.local/bin/uv run python browse.py

#   sudo systemctl status evidenceplatform   # Check status
#   sudo systemctl restart evidenceplatform  # Restart
#   sudo systemctl stop evidenceplatform     # Stop
#   sudo journalctl -u evidenceplatform -f   # View logs (live)

# nginx
sudo apt-get install nginx -y

sudo cp /home/dave/infra/nginx.conf /etc/nginx/sites-available/default

sudo systemctl enable nginx
sudo systemctl restart nginx


## HELPER scripts
export ENVIRONMENT=production
export DB_USER=golf
export DB_PASS=password5
export DB_NAME=evidenceplatform
export DB_PORT=3306
export DB_HOST=localhost
export DEFAULT_SIGNATURE=your_prod_signature
export BROWSING_PLATFORM_DEV=0

# add new user (have got my demo one already in the insert_data.sql)
#  uv run python -m browsing_platform.server.scripts.add_user

# insert data from archives
# uv run python extractors/archives_db_loader.py
uv run python db_loaders/archives_db_loader.py

# uv run python extractors/archives_db_loader.py 2>&1 | tee output.log
