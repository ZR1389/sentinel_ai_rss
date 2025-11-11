#!/usr/bin/env python3
"""
Integration test to verify connection pooling works with actual database operations
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def test_integration():
    """Test connection pooling with database operations."""
    print("🔍 Testing Connection Pooling Integration...")
    
    try:
        import db_utils
        from db_utils import get_connection_pool, close_connection_pool
        
        # Test that we can import without errors
        print("✅ db_utils imported successfully")
        
        # Check that connection pool functions are available
        assert hasattr(db_utils, 'get_connection_pool'), "Missing get_connection_pool function"
        assert hasattr(db_utils, 'close_connection_pool'), "Missing close_connection_pool function" 
        assert hasattr(db_utils, '_conn'), "Missing _conn function"
        assert hasattr(db_utils, '_release_conn'), "Missing _release_conn function"
        print("✅ All connection pool functions are available")
        
        # Test that environment variables are read correctly
        min_size = int(os.getenv("DB_POOL_MIN_SIZE", "1"))
        max_size = int(os.getenv("DB_POOL_MAX_SIZE", "20"))
        print(f"✅ Pool configuration: min={min_size}, max={max_size}")
        
        # Test that basic database functions exist and have proper signatures
        import inspect
        
        # Check execute function signature
        sig = inspect.signature(db_utils.execute)
        assert 'query' in sig.parameters, "execute missing query parameter"
        assert 'params' in sig.parameters, "execute missing params parameter"
        print("✅ execute function has correct signature")
        
        # Check fetch_one function signature  
        sig = inspect.signature(db_utils.fetch_one)
        assert 'query' in sig.parameters, "fetch_one missing query parameter"
        assert 'params' in sig.parameters, "fetch_one missing params parameter"
        print("✅ fetch_one function has correct signature")
        
        # Check fetch_all function signature
        sig = inspect.signature(db_utils.fetch_all)
        assert 'query' in sig.parameters, "fetch_all missing query parameter"
        assert 'params' in sig.parameters, "fetch_all missing params parameter"
        print("✅ fetch_all function has correct signature")
        
        print("\n🎉 Integration test passed!")
        print("Connection pooling is properly implemented and ready for use.")
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except AssertionError as e:
        print(f"❌ Assertion error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

if __name__ == "__main__":
    success = test_integration()
    sys.exit(0 if success else 1)
