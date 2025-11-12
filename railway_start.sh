#!/bin/bash
# railway_start.sh - Absolute override for Railway deployment

echo "🚀 FORCING FastAPI Health Server Start"
echo "Railway Environment: $RAILWAY_ENVIRONMENT"
echo "Port: $PORT"
echo "Database URL exists: $([ -n "$DATABASE_URL" ] && echo "YES" || echo "NO")"

# Kill any existing processes (just in case)
pkill -f gunicorn || true
pkill -f uvicorn || true

# Ensure we're in the right directory
cd /app || cd .

# Force start with uvicorn - no other options
echo "Starting uvicorn with railway_health:app..."
exec /opt/venv/bin/uvicorn railway_health:app \
    --host 0.0.0.0 \
    --port ${PORT:-8080} \
    --log-level info \
    --no-access-log
