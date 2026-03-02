#!/bin/bash
# Launch the High-Z Filterbank Live Viewer
# Usage: ./run_live_viewer.sh [--port PORT] [--refresh SECONDS]

cd "$(dirname "$0")"
pipenv run python src/viewers/live_viewer.py "$@"
