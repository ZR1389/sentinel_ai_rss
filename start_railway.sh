#!/bin/bash
# start_railway.sh - Railway startup script that handles PORT environment variable

set -e

# Get port from Railway environment or default to 8080
PORT=${PORT:-8080}

echo "Starting Sentinel AI Railway Health Server on port $PORT"
echo "Environment: ${RAILWAY_ENVIRONMENT:-development}"
echo "Database URL configured: $([ -n "$DATABASE_URL" ] && echo "Yes" || echo "No")"

# Start the FastAPI health server with uvicorn
exec uvicorn railway_health:app --host 0.0.0.0 --port $PORT --log-level info
