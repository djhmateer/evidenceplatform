#!/bin/bash

# bash script for installing on Ubuntu 24 on dev and prod

# assume sudo apt update and upgrade have already been run

# pyenv - simple python version managment
# don't need on production if just need a single version of python eg 3.14.0
# I need on dev as have a separate projects needed spearate versions of python
# https://github.com/pyenv/pyenv

# 2.16.12 on 17th Nov 25
pyenv 

# update
pyenv update
 
# install (not update)
curl -fsSL https://pyenv.run | bash


echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
echo '[[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bashrc
echo 'eval "$(pyenv init - bash)"' >> ~/.bashrc

echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.profile
echo '[[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.profile
echo 'eval "$(pyenv init - bash)"' >> ~/.profile

## restart shell (careful in automated scripts)
exec "$SHELL"

# this downloads and compiles the python version
# pyenv install 3.13.5

# list available versions
# there is a t version, which means tuned. don't use yet.
pyenv install -l

# install python dependencies before attempting to install new python version
sudo apt update; sudo apt install make build-essential libssl-dev zlib1g-dev \
libbz2-dev libreadline-dev libsqlite3-dev curl git \
libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev

# latest stable as of 17th Nov 25
pyenv install 3.14.0

# I want to keep 3.12.3 as my default, 
# but I found global system had shim errors when running my test python program 
# so best to use 3.12.3 specifically
# pyenv global system
pyenv global 3.12.3

# show locally installed versions
pyenv versions

# if on dev, select the appropriate python version ie pyenv 3.14.0
# ie not pypoetry 3.12.3

##
### Python Dependencies 
# there are many in requirements.txt and don't want to affect other projects
# on my system, so use a virtual environment
# todo - move to uv? keep poetry for now as working. will allow me to get rid of __init__.py files

curl -sSL https://install.python-poetry.org | python3 -

# update poetry
poetry self update

# 2.2.1 on 17th Nov 25
poetry --version

# initialize poetry in the project folder
# poetry init

# install first time (or if major changes to pyproject.toml)
# ****TODO - there are vulnerabilities in some dependencies, need to fix****
# poetry run safety check
poetry install 

# update dependencies
poetry update


##
## React / Nodejs dependencies
## only need to do this for dev? or to build the frontend for deployment on prod

# install nvm - node version manager

# https://github.com/nvm-sh/nvm
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash

nvm install --lts --latest-npm

# 24.11.1 on 17th Nov 25
node -v

# 11.6.2
npm -v  

cd browsing_platform/client

# todo - favour pnpm

# using React 18.2.0 (why not 19?)
# creates node_modules
npm install --legacy-peer-deps

npm update --legacy-peer-deps

npm start



## MySQL
## https://documentation.ubuntu.com/server/how-to/databases/install-mysql/


# 8.0.43-0ubuntu0.24.04.2 on 18th Nov 25
sudo apt install mysql-server

# check mysql is running
sudo service mysql status

sudo systemctl restart mysql.service

# comment out bind-address = localhost  to allow remote connections
sudo vi /etc/mysql/mysql.conf.d/mysqld.cnf


# default install has no root password, so just connect as root user using auth_socket
sudo mysql -u root

# CREATE USER 'bob'@'localhost' IDENTIFIED WITH caching_sha2_password BY 'password';

# CREATE USER 'alice' IDENTIFIED WITH caching_sha2_password BY 'password';

# so can access from Windows on WSL2
CREATE USER 'charlie'@'%' IDENTIFIED WITH caching_sha2_password BY 'password';

GRANT ALL PRIVILEGES ON *.* TO 'charlie'@'%' WITH GRANT OPTION;
FLUSH PRIVILEGES;

# on my test prod box (130) lets use a different user 
CREATE USER 'doug'@'%' IDENTIFIED WITH caching_sha2_password BY 'password2';

GRANT ALL PRIVILEGES ON *.* TO 'doug'@'%' WITH GRANT OPTION;
FLUSH PRIVILEGES;

# prod prod
# CREATE USER 'ellie'@'%' IDENTIFIED WITH caching_sha2_password BY 'password3';

# GRANT ALL PRIVILEGES ON *.* TO 'ellie'@'%' WITH GRANT OPTION;
# FLUSH PRIVILEGES;




# this would give shutdown, replication etc..
# GRANT SUPER ON *.* TO 'bob'@'localhost';

# GRANT ALL PRIVILEGES ON *.* TO 'bob'@'localhost' WITH GRANT OPTION;
# FLUSH PRIVILEGES;

# test user from wsl2
mysql -u charlie -p


## CREATE DB
## see browsing_platform/server/scripts/create_db.sql

# then run browing_platform/server/scripts/add_user.py      



# create archives directory
mkdir -p /home/dave/code/evidenceplatform/archives
mkdir -p /home/dave/code/evidenceplatform/thumbnails

#
## Run Server
# in browsing_platform/client
# localhost:3000
npm start

# run /browse.py
# Uvicorn running on http://127.0.0.1:4444 
