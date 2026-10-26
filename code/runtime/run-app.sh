#!/bin/bash

cd /mnt/Personal/Repository/Anarchy-Chess/code || exit 1

source /mnt/Local/Virtual_Environments/Python_3.12/bin/activate

exec uvicorn main:app --host 127.0.0.1 --port 8000
