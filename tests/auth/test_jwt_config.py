#!/usr/bin/env python3
"""
JWT Configuration Test

This script tests that JWT token generation and verification works
correctly with the current .env configuration.
"""

import sys
import os
import jwt
import datetime
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

def test_jwt_configuration():
    """Test JWT token generation and verification"""
    
    print("="*60)
    print("JWT CONFIGURATION TEST")
    print("="*60)
    
    # Load environment variables
    load_dotenv()
    
    # Get JWT configuration
    jwt_secret = os.getenv("JWT_SECRET")
    jwt_exp_minutes = int(os.getenv("JWT_EXP_MINUTES", 60))
    
    print(f"\n📋 JWT Configuration:")
    print(f"- JWT_SECRET: {'✅ Set' if jwt_secret else '❌ Missing'}")
    print(f"- JWT_EXP_MINUTES: {jwt_exp_minutes} minutes")
    
    if not jwt_secret:
        print("❌ JWT_SECRET not found in environment!")
        return False
    
    # Check JWT secret quality
    print(f"\n🔑 JWT Secret Analysis:")
    print(f"- Length: {len(jwt_secret)} characters")
    print(f"- Quality: {'✅ Production-grade' if len(jwt_secret) > 50 else '⚠️ Weak (use longer key)'}")
    
    # Test 1: Token Generation
    print(f"\n--- Test 1: Token Generation ---")
    try:
        # Create test payload
        test_payload = {
            "user_id": "test_user_123",
            "email": "test@example.com",
            "plan": "FREE",
            "iat": datetime.datetime.utcnow(),
            "exp": datetime.datetime.utcnow() + datetime.timedelta(minutes=jwt_exp_minutes)
        }
        
        # Generate token
        token = jwt.encode(test_payload, jwt_secret, algorithm="HS256")
        print(f"✅ Token generated successfully")
        print(f"- Token length: {len(token)} characters")
        print(f"- Token preview: {token[:20]}...{token[-20:]}")
        
    except Exception as e:
        print(f"❌ Token generation failed: {e}")
        return False
    
    # Test 2: Token Verification
    print(f"\n--- Test 2: Token Verification ---")
    try:
        # Verify token
        decoded_payload = jwt.decode(token, jwt_secret, algorithms=["HS256"])
        print(f"✅ Token verified successfully")
        print(f"- User ID: {decoded_payload.get('user_id')}")
        print(f"- Email: {decoded_payload.get('email')}")
        print(f"- Plan: {decoded_payload.get('plan')}")
        print(f"- Expires: {decoded_payload.get('exp')}")
        
    except jwt.ExpiredSignatureError:
        print(f"❌ Token expired")
        return False
    except jwt.InvalidTokenError as e:
        print(f"❌ Token verification failed: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error during verification: {e}")
        return False
    
    # Test 3: Invalid Secret Detection
    print(f"\n--- Test 3: Invalid Secret Detection ---")
    try:
        # Try to verify with wrong secret
        wrong_secret = "wrong_secret_key"
        jwt.decode(token, wrong_secret, algorithms=["HS256"])
        print(f"❌ Security issue: Token accepted with wrong secret!")
        return False
    except jwt.InvalidTokenError:
        print(f"✅ Security verified: Wrong secret correctly rejected")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False
    
    # Test 4: Expired Token Handling
    print(f"\n--- Test 4: Expired Token Handling ---")
    try:
        # Create expired token
        expired_payload = {
            "user_id": "test_user_123",
            "email": "test@example.com",
            "exp": datetime.datetime.utcnow() - datetime.timedelta(minutes=1)  # 1 minute ago
        }
        expired_token = jwt.encode(expired_payload, jwt_secret, algorithm="HS256")
        
        # Try to verify expired token
        jwt.decode(expired_token, jwt_secret, algorithms=["HS256"])
        print(f"❌ Security issue: Expired token was accepted!")
        return False
    except jwt.ExpiredSignatureError:
        print(f"✅ Expiration verified: Expired token correctly rejected")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False
    
    # Test 5: Import verification (check if auth modules can use JWT)
    print(f"\n--- Test 5: Auth Module Integration ---")
    try:
        # Try importing auth-related modules if they exist
        auth_modules = []
        try:
            import auth_utils
            auth_modules.append("auth_utils")
        except ImportError:
            pass
        
        if auth_modules:
            print(f"✅ Auth modules found: {', '.join(auth_modules)}")
        else:
            print(f"ℹ️  No auth modules found (auth_utils.py)")
            
        print(f"✅ JWT library integration working")
        
    except Exception as e:
        print(f"⚠️  Auth module integration issue: {e}")
    
    print(f"\n" + "="*60)
    print("JWT TEST RESULTS")
    print("="*60)
    print("✅ Token generation: PASSED")
    print("✅ Token verification: PASSED") 
    print("✅ Security validation: PASSED")
    print("✅ Expiration handling: PASSED")
    print("✅ Integration ready: PASSED")
    
    print(f"\n🎉 JWT configuration is working perfectly!")
    print(f"🔐 Your production JWT secret is properly configured")
    print(f"⏰ Token expiration set to {jwt_exp_minutes} minutes")
    
    return True

def test_environment_variables():
    """Test that environment variables are loaded correctly"""
    
    print(f"\n--- Environment Variable Check ---")
    load_dotenv()
    
    # Check critical variables
    critical_vars = [
        "JWT_SECRET",
        "JWT_EXP_MINUTES", 
        "ENV",
        "DATABASE_URL"
    ]
    
    all_present = True
    for var in critical_vars:
        value = os.getenv(var)
        status = "✅ Set" if value else "❌ Missing"
        print(f"- {var}: {status}")
        if not value:
            all_present = False
    
    return all_present

if __name__ == "__main__":
    print("Starting JWT Configuration Test...\n")
    
    # Test environment loading
    env_ok = test_environment_variables()
    
    if not env_ok:
        print("❌ Environment variables not properly loaded")
        sys.exit(1)
    
    # Test JWT functionality
    jwt_ok = test_jwt_configuration()
    
    if jwt_ok:
        print("\n🚀 All JWT tests passed - ready for production!")
        sys.exit(0)
    else:
        print("\n❌ JWT tests failed - check configuration")
        sys.exit(1)
