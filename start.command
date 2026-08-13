#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

(sleep 1; open "http://127.0.0.1:${PORT:-5050}") &
exec ./run.sh
