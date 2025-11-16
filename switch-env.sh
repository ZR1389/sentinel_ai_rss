#!/bin/bash
# Quick environment switcher for Sentinel AI

set -e

case "$1" in
  dev|development)
    cp .env.development .env
    echo "✅ Switched to DEVELOPMENT mode"
    echo "   - SQLite database"
    echo "   - DeepSeek LLM only"
    echo "   - External services disabled"
    echo "   - Safe for local testing"
    ;;
    
  prod|production)
    echo "⚠️  WARNING: Switching to PRODUCTION mode"
    echo "   This will use:"
    echo "   - Railway PostgreSQL"
    echo "   - All LLM providers (costs money)"
    echo "   - ACLED, Apify, SOCMINT (burns quotas)"
    echo ""
    read -p "Are you sure? (type 'yes' to confirm): " confirm
    if [ "$confirm" = "yes" ]; then
      cp .env.production .env
      echo "✅ Switched to PRODUCTION mode"
      echo "   BE CAREFUL - you're using real services!"
    else
      echo "❌ Cancelled"
      exit 1
    fi
    ;;
    
  status)
    echo "Current environment settings:"
    echo "----------------------------"
    grep -E "^ENV=|^DATABASE_URL=|^APIFY_API_TOKEN=|^ACLED_ENABLED=" .env || echo "No .env file found"
    ;;
    
  *)
    echo "Sentinel AI Environment Switcher"
    echo "Usage: $0 {dev|prod|status}"
    echo ""
    echo "Commands:"
    echo "  dev     - Switch to development (safe, local)"
    echo "  prod    - Switch to production (Railway, costs money)"
    echo "  status  - Show current environment"
    exit 1
    ;;
esac
