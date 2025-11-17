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

### Dependencies 
# there are many in requirements.txt and don't want to affect other projects
# on my system, so use a virtual environment

curl -sSL https://install.python-poetry.org | python3 -

# update poetry
poetry self update

# 2.2.1 on 17th Nov 25
poetry --version

# initialize poetry in the project folder
poetry init
