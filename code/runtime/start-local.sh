#!/bin/bash

cd /mnt/Personal/Repository/Anarchy-Chess/code || exit 1
cloudflared tunnel --url http://localhost:8000
