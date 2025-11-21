#!/bin/bash
# Deploy Stats API Enhancements to Railway

set -e

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Stats API Enhancement Deployment                        ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# Check if we're in git repo
if [ ! -d .git ]; then
    echo "❌ Error: Not in a git repository"
    exit 1
fi

# Check for uncommitted changes
if [[ -n $(git status -s) ]]; then
    echo "📝 Uncommitted changes detected:"
    git status -s
    echo ""
    read -p "Continue with commit? (y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 1
    fi
fi

echo "📦 Files to be committed:"
echo "  - main.py (enhanced /api/stats/overview endpoint)"
echo "  - STATS_API_SUMMARY.md"
echo "  - FRONTEND_STATS_INTEGRATION.md"
echo "  - STATS_API_QUICK_REF.md"
echo "  - test_stats_endpoint.py"
echo ""

# Stage files
echo "🔄 Staging files..."
git add main.py
git add STATS_API_SUMMARY.md
git add FRONTEND_STATS_INTEGRATION.md
git add STATS_API_QUICK_REF.md
git add test_stats_endpoint.py
git add CONTEXT_API_IMPLEMENTATION.md DEPLOYMENT_GUIDE_CONTEXT_API.md 2>/dev/null || true
git add migrate_user_context.sql 2>/dev/null || true

# Commit
echo "💾 Committing changes..."
git commit -m "feat: enhance stats API with plan limits, severity percentages, alert-based locations

- Add plan-based window_days limits (FREE=7d, PRO=30d, ENT=90d)
- Include per-severity percentages in severity_breakdown
- Change tracked_locations to count distinct alert locations
- Add max_window_days field for frontend plan differentiation
- Update caching to include user email in cache key
- Add comprehensive frontend integration documentation
- Include test utility for endpoint validation"

echo "✅ Committed successfully"
echo ""

# Push
echo "🚀 Pushing to origin/main..."
read -p "Push to Railway now? (y/N) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    git push origin main
    echo "✅ Pushed to Railway"
    echo ""
    echo "⏳ Waiting for Railway deployment..."
    echo "   Check status: https://railway.app/dashboard"
    echo ""
    sleep 5
    
    # Test endpoint
    echo "🧪 Test the endpoint after deployment (1-2 minutes):"
    echo ""
    echo "   export TOKEN=\"your_jwt_token\""
    echo "   curl -H \"Authorization: Bearer \$TOKEN\" \\"
    echo "     https://sentinelairss-production.up.railway.app/api/stats/overview"
    echo ""
    echo "   OR run: python test_stats_endpoint.py"
    echo ""
else
    echo "⏸️  Push skipped. Run 'git push origin main' when ready."
fi

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Next Steps                                              ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "1. ✅ Backend deployed with enhanced stats endpoint"
echo "2. 📖 Review frontend integration guide:"
echo "      - FRONTEND_STATS_INTEGRATION.md"
echo "3. 🧪 Test endpoint with different plan levels"
echo "4. 🎨 Build frontend dashboard components"
echo "5. 📊 Integrate charts (Chart.js/Recharts)"
echo "6. 💰 Add plan upgrade prompts for FREE users"
echo "7. 📱 Test mobile responsive design"
echo "8. 🔄 Set up auto-refresh (2-5 minute intervals)"
echo ""
echo "✨ Deployment complete!"
