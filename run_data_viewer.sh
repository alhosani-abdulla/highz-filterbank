#!/bin/bash
# Launch the High-Z Filterbank Data Viewer
# Usage: ./run_data_viewer.sh [--port PORT]

cd "$(dirname "$0")"
pipenv run python src/viewers/data_viewer.py "$@"
