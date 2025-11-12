#!/bin/bash
# entrypoint.sh - Force Railway to use FastAPI health server

echo "🚀 Starting Sentinel AI with FastAPI health server..."
echo "Environment: $RAILWAY_ENVIRONMENT"
echo "Port: $PORT"

# Start FastAPI health server with uvicorn
exec uvicorn railway_health:app --host 0.0.0.0 --port ${PORT:-8080} --log-level info
