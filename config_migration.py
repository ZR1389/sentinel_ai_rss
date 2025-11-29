#!/usr/bin/env python3
"""
Configuration Migration Script

This script helps identify remaining os.getenv() calls that should be migrated 
to use the centralized CONFIG object from config.py.

Run this script to see which files still have environment variable fallbacks.
"""

import os
import re
import glob
from pathlib import Path

def find_os_getenv_usage():
    """Find all os.getenv() usage in Python files."""
    
    python_files = glob.glob("*.py") + glob.glob("**/*.py", recursive=True)
    
    # Exclude certain files that legitimately need os.getenv
    exclude_patterns = [
        "config.py",  # This file manages environment variables
        "railway_cron.py",  # Needs direct env access for cron setup
        "test_*.py",  # Test files may need direct env access
        ".venv/",  # Virtual environment
        "__pycache__/",  # Compiled Python
        ".git/",  # Git directory
    ]
    
    results = []
    
    for file_path in python_files:
        # Skip excluded files
        if any(pattern in file_path for pattern in exclude_patterns):
            continue
            
        try:
            with open(file_path, 'r') as f:
                content = f.read()
                
            # Find os.getenv usage
            pattern = r'os\.getenv\s*\(\s*["\']([^"\']+)["\'](?:\s*,\s*[^)]+)?\s*\)'
            matches = re.findall(pattern, content)
            
            if matches:
                results.append({
                    'file': file_path,
                    'env_vars': matches,
                    'count': len(matches)
                })
                
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
    
    return results

def suggest_config_mapping(env_var):
    """Suggest the CONFIG attribute for a given environment variable."""
    
    mappings = {
        # Database
        'DATABASE_URL': 'CONFIG.database.url',
        'DB_POOL_MIN_SIZE': 'CONFIG.database.pool_min_size',
        'DB_POOL_MAX_SIZE': 'CONFIG.database.pool_max_size',
        
        # LLM
        'OPENAI_API_KEY': 'CONFIG.llm.openai_api_key',
        'XAI_API_KEY': 'CONFIG.llm.xai_api_key',
        'DEEPSEEK_API_KEY': 'CONFIG.llm.deepseek_api_key',
        'MOONSHOT_API_KEY': 'CONFIG.llm.moonshot_api_key',
        'XAI_MODEL': 'CONFIG.llm.xai_model',
        'XAI_TEMPERATURE': 'CONFIG.llm.xai_temperature',
        'ADVISOR_TEMPERATURE': 'CONFIG.llm.advisor_temperature',
        
        # Email
        'BREVO_API_KEY': 'CONFIG.email.brevo_api_key',
        'BREVO_SENDER_EMAIL': 'CONFIG.email.brevo_sender_email',
        'NEWSLETTER_LIST_ID': 'CONFIG.email.newsletter_list_id',
        'VERIFY_FROM_EMAIL': 'CONFIG.email.verify_from_email',
        'SITE_NAME': 'CONFIG.email.site_name',
        
        # Telegram
        'TELEGRAM_BOT_TOKEN': 'CONFIG.telegram.bot_token',
        'TELEGRAM_CHAT_ID': 'CONFIG.telegram.chat_id',
        'TELEGRAM_PUSH_ENABLED': 'CONFIG.telegram.push_enabled',
        'TELEGRAM_API_ID': 'CONFIG.telegram.api_id',
        'TELEGRAM_API_HASH': 'CONFIG.telegram.api_hash',
        
        # Application
        'PORT': 'CONFIG.app.port',
        'ALLOWED_ORIGINS': 'CONFIG.app.allowed_origins',
        'DEFAULT_PLAN': 'CONFIG.app.default_plan',
        'ALERT_RETENTION_DAYS': 'CONFIG.app.alert_retention_days',
        'EMBEDDING_QUOTA_DAILY': 'CONFIG.app.embedding_quota_daily',
        'REDIS_URL': 'CONFIG.app.redis_url',
        'METRICS_ENABLED': 'CONFIG.app.metrics_enabled',
        
        # Security
        'JWT_SECRET': 'CONFIG.security.jwt_secret',
        'JWT_EXP_MINUTES': 'CONFIG.security.jwt_exp_minutes',
        'LOG_LEVEL': 'CONFIG.security.log_level',
        'STRUCTURED_LOGGING': 'CONFIG.security.structured_logging',
        
        # RSS (already in CONFIG.rss)
        'RSS_TIMEOUT_SEC': 'CONFIG.rss.timeout_sec',
        'RSS_CONCURRENCY': 'CONFIG.rss.max_concurrency',
        'RSS_BATCH_LIMIT': 'CONFIG.rss.batch_limit',
        'RSS_USE_FULLTEXT': 'CONFIG.rss.use_fulltext',
        'CITYUTILS_ENABLE_GEOCODE': 'CONFIG.rss.geocode_enabled',
    }
    
    return mappings.get(env_var, f"# TODO: Add {env_var} to config.py")

def main():
    """Main migration analysis."""
    
    print("🔍 Scanning for environment variable fallbacks...")
    print("=" * 60)
    
    results = find_os_getenv_usage()
    
    if not results:
        print("✅ No os.getenv() usage found! Configuration is fully centralized.")
        return
    
    total_files = len(results)
    total_vars = sum(r['count'] for r in results)
    
    print(f"Found {total_vars} environment variable references in {total_files} files:")
    print()
    
    for result in results:
        print(f"📁 {result['file']} ({result['count']} variables)")
        
        for env_var in result['env_vars']:
            suggestion = suggest_config_mapping(env_var)
            print(f"   • {env_var} → {suggestion}")
        print()
    
    print("🔧 Migration Steps:")
    print("1. Import CONFIG: from core.config import CONFIG")
    print("2. Replace os.getenv() calls with CONFIG attributes")
    print("3. Add missing variables to config.py if needed")
    print("4. Test the application to ensure all configs work")
    print()
    print("📖 Benefits of centralized configuration:")
    print("   • Eliminates environment variable fallbacks")
    print("   • Improves type safety and validation")
    print("   • Makes configuration dependencies explicit")
    print("   • Enables better testing with mock configurations")

if __name__ == "__main__":
    main()
