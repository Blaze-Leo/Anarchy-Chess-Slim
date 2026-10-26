#!/bin/bash

cd /mnt/Local/AI || exit 1
cloudflared tunnel --url http://localhost:8000
