#!/bin/sh
set -eu

if [ ! -f /app/config.json ]; then
  printf '%s\n' 'config.json not found. Copy config.example.json to config.json and fill in the required values.' >&2
  exit 1
fi

mkdir -p /app/data /app/files /app/logs/sessions

exec python /app/main.py
