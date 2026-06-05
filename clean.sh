#!/bin/bash
# Delegate to Python app for cleaner, portable implementation
cd "$(dirname "$0")"
exec python3 app.py clean "$@"