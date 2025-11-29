#!/bin/bash
# Railway cron wrapper - ensures DATABASE_PUBLIC_URL overrides any sqlite config
# Usage: run_cron.sh <operation>
# Example: run_cron.sh engine

set -e

# Force DATABASE_URL from DATABASE_PUBLIC_URL if available
if [ -n "$DATABASE_PUBLIC_URL" ]; then
    export DATABASE_URL="$DATABASE_PUBLIC_URL"
fi

# Validate DATABASE_URL is set and not sqlite
if [ -z "$DATABASE_URL" ]; then
    echo "ERROR: DATABASE_URL or DATABASE_PUBLIC_URL must be set"
    exit 1
fi

if [[ "$DATABASE_URL" == sqlite* ]]; then
    echo "ERROR: DATABASE_URL is sqlite - cron jobs require PostgreSQL"
    exit 1
fi

# Run the cron operation
python railway_cron.py "$@"
