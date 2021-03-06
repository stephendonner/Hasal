#!/bin/bash
# HASAL_WORKSPACE is the Hasal path in current environment

cd $HASAL_WORKSPACE

git checkout master
git pull
pip install -U pip
pip install -Ur tools/requirements.txt

python tools/trigger_build.py
