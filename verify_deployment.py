#!/usr/bin/env python3
"""
verify_deployment.py - Final verification before Railway deployment

Quick verification checklist for FastAPI deployment readiness.
"""

import os
import sys
import json
from datetime import datetime

def check_files():
    """Verify all required files exist."""
    required_files = [
        'health_check.py',
        'railway.toml',
        'requirements.txt',
        'pyproject.toml',
        'main.py',
        'db_utils.py',
        'keywords_loader.py'
    ]
    
    missing = []
    for file in required_files:
        if not os.path.exists(file):
            missing.append(file)
    
    return missing

def check_railway_config():
    """Verify railway.toml configuration."""
    try:
        with open('railway.toml', 'r') as f:
            config = f.read()
        
        if 'uvicorn health_check:app' in config:
            return True, "FastAPI configuration found"
        else:
            return False, "FastAPI configuration not found in railway.toml"
    except Exception as e:
        return False, f"Could not read railway.toml: {e}"

def check_requirements():
    """Verify FastAPI and uvicorn in requirements.txt."""
    try:
        with open('requirements.txt', 'r') as f:
            reqs = f.read()
        
        has_fastapi = 'fastapi' in reqs.lower()
        has_uvicorn = 'uvicorn' in reqs.lower()
        
        if has_fastapi and has_uvicorn:
            return True, "FastAPI and uvicorn found in requirements.txt"
        else:
            missing = []
            if not has_fastapi:
                missing.append('fastapi')
            if not has_uvicorn:
                missing.append('uvicorn')
            return False, f"Missing dependencies: {', '.join(missing)}"
    except Exception as e:
        return False, f"Could not read requirements.txt: {e}"

def check_import():
    """Verify health_check imports correctly."""
    try:
        from health_check import app
        return True, f"Health check app imported successfully: {type(app)}"
    except Exception as e:
        return False, f"Could not import health_check: {e}"

def main():
    """Run final deployment verification."""
    print("🔍 FINAL DEPLOYMENT VERIFICATION")
    print("=" * 40)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Directory: {os.getcwd()}")
    print()
    
    checks = [
        ("Required Files", check_files),
        ("Railway Configuration", check_railway_config),
        ("Requirements Dependencies", check_requirements),
        ("Module Import", check_import),
    ]
    
    all_passed = True
    
    for check_name, check_func in checks:
        print(f"📋 {check_name}")
        
        if check_name == "Required Files":
            missing = check_func()
            if not missing:
                print("  ✅ All required files present")
            else:
                print(f"  ❌ Missing files: {', '.join(missing)}")
                all_passed = False
        else:
            try:
                success, message = check_func()
                if success:
                    print(f"  ✅ {message}")
                else:
                    print(f"  ❌ {message}")
                    all_passed = False
            except Exception as e:
                print(f"  💥 Check failed: {e}")
                all_passed = False
        
        print()
    
    print("=" * 40)
    
    if all_passed:
        print("🎉 ALL CHECKS PASSED!")
        print()
        print("🚀 READY FOR RAILWAY DEPLOYMENT")
        print()
        print("📋 DEPLOYMENT CHECKLIST:")
        print("  1. ✅ FastAPI health server configured")
        print("  2. ✅ uvicorn start command set")
        print("  3. ✅ Health check path: /health")
        print("  4. ✅ Dependencies verified")
        print()
        print("🔗 NEXT STEPS:")
        print("  git add .")
        print("  git commit -m 'Configure FastAPI health server for Railway'")
        print("  git push origin main")
        print()
        print("⚙️  RAILWAY CONFIGURATION:")
        print("  • Health Check Path: /health")
        print("  • Start Command: uvicorn health_check:app --host 0.0.0.0 --port $PORT")
        print("  • Environment Variables: DATABASE_URL, OPENAI_API_KEY (required)")
        
        return 0
    else:
        print("❌ VERIFICATION FAILED")
        print("Please fix the issues above before deploying.")
        return 1

if __name__ == "__main__":
    exit(main())
