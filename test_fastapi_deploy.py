#!/usr/bin/env python3
"""
test_fastapi_deploy.py - Test FastAPI health server deployment readiness

Tests:
- FastAPI app imports correctly
- uvicorn can start the server
- Health endpoint responds
- Railway deployment compatibility
"""

import os
import sys
import time
import threading
import requests
import subprocess
from datetime import datetime

def test_imports():
    """Test that all required imports work."""
    print("🧪 Testing imports...")
    
    try:
        import fastapi
        print(f"  ✅ FastAPI {fastapi.__version__}")
    except ImportError as e:
        print(f"  ❌ FastAPI import failed: {e}")
        return False
    
    try:
        import uvicorn
        print(f"  ✅ uvicorn {uvicorn.__version__}")
    except ImportError as e:
        print(f"  ❌ uvicorn import failed: {e}")
        return False
    
    try:
        from health_check import app
        print(f"  ✅ health_check app: {type(app)}")
    except ImportError as e:
        print(f"  ❌ health_check import failed: {e}")
        return False
    
    return True

def test_uvicorn_command():
    """Test the Railway start command."""
    print("🚀 Testing Railway start command...")
    
    # This is the command Railway will use
    cmd = "uvicorn health_check:app --host 0.0.0.0 --port 8001"
    
    print(f"  Command: {cmd}")
    
    # Start server in background
    proc = None
    try:
        # Use environment python path
        python_path = sys.executable.replace('python', '')
        env = os.environ.copy()
        env['PATH'] = python_path + ':' + env.get('PATH', '')
        
        proc = subprocess.Popen(
            cmd.split(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env
        )
        
        # Wait for server to start
        time.sleep(3)
        
        # Test health endpoint
        response = requests.get('http://127.0.0.1:8001/health', timeout=5)
        print(f"  ✅ Server started, health endpoint status: {response.status_code}")
        
        # Test root endpoint
        response = requests.get('http://127.0.0.1:8001/', timeout=5)
        print(f"  ✅ Root endpoint status: {response.status_code}")
        
        return True
        
    except requests.exceptions.ConnectionError:
        print("  ❌ Could not connect to server")
        return False
    except Exception as e:
        print(f"  ❌ Server test failed: {e}")
        return False
    finally:
        if proc:
            proc.terminate()
            time.sleep(1)
            if proc.poll() is None:
                proc.kill()

def test_environment_handling():
    """Test how the health check handles missing environment variables."""
    print("🔧 Testing environment handling...")
    
    try:
        from health_check import perform_health_check
        
        # Test without required env vars
        health_result = perform_health_check()
        
        print(f"  Status: {health_result['status']}")
        print(f"  Issues count: {len(health_result['issues'])}")
        
        # Should be unhealthy due to missing env vars, but not crash
        if health_result['status'] == 'unhealthy' and len(health_result['issues']) > 0:
            print("  ✅ Properly handles missing environment variables")
            return True
        else:
            print("  ❌ Unexpected health check result")
            return False
            
    except Exception as e:
        print(f"  ❌ Health check failed: {e}")
        return False

def main():
    """Run all deployment readiness tests."""
    print("=" * 60)
    print("🏗️  SENTINEL AI - FASTAPI DEPLOYMENT READINESS TEST")
    print("=" * 60)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Python: {sys.executable}")
    print(f"Working directory: {os.getcwd()}")
    print()
    
    tests = [
        ("Import Tests", test_imports),
        ("uvicorn Command Test", test_uvicorn_command),
        ("Environment Handling", test_environment_handling),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"🧪 {test_name}")
        print("-" * 40)
        
        try:
            if test_func():
                print(f"✅ {test_name} PASSED")
                passed += 1
            else:
                print(f"❌ {test_name} FAILED")
        except Exception as e:
            print(f"💥 {test_name} CRASHED: {e}")
        
        print()
    
    print("=" * 60)
    print(f"📊 RESULTS: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 ALL TESTS PASSED - READY FOR RAILWAY DEPLOYMENT!")
        print()
        print("🚀 DEPLOYMENT COMMANDS:")
        print("  git add .")
        print("  git commit -m 'Deploy FastAPI health server'")
        print("  git push origin main")
        print()
        print("🔗 Railway will use:")
        print("  Start command: uvicorn health_check:app --host 0.0.0.0 --port $PORT")
        print("  Health check: /health")
        return 0
    else:
        print("❌ Some tests failed - review issues before deployment")
        return 1

if __name__ == "__main__":
    exit(main())
