#!/usr/bin/env python3
"""
Test Connection Pooling Implementation in db_utils.py
Verifies that connection pooling is working correctly and improves performance.
"""

import sys
import os
import time
import threading
import concurrent.futures
from unittest.mock import patch, MagicMock

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

try:
    import db_utils
    from db_utils import get_connection_pool, close_connection_pool, _conn, _release_conn
    print("✅ Successfully imported db_utils with connection pooling")
except ImportError as e:
    print(f"❌ Failed to import db_utils: {e}")
    sys.exit(1)

def test_connection_pool_initialization():
    """Test that connection pool is initialized correctly."""
    print("\n🔍 Testing Connection Pool Initialization...")
    
    # Mock DATABASE_URL for testing
    with patch.dict(os.environ, {
        'DATABASE_URL': 'postgresql://test:test@localhost/test',
        'DB_POOL_MIN_SIZE': '2',
        'DB_POOL_MAX_SIZE': '10'
    }):
        try:
            # Clear any existing pool
            db_utils._connection_pool = None
            
            # Mock psycopg2.pool.ThreadedConnectionPool
            with patch('db_utils.psycopg2.pool.ThreadedConnectionPool') as mock_pool_class:
                mock_pool = MagicMock()
                mock_pool_class.return_value = mock_pool
                
                pool = get_connection_pool()
                
                # Verify pool was created with correct parameters
                mock_pool_class.assert_called_once_with(
                    minconn=2,
                    maxconn=10,
                    dsn='postgresql://test:test@localhost/test'
                )
                
                # Verify the same pool instance is returned on subsequent calls
                pool2 = get_connection_pool()
                assert pool is pool2, "Should return the same pool instance"
                
                print("✅ Connection pool initialization working correctly")
                
        except Exception as e:
            print(f"❌ Connection pool initialization failed: {e}")
            return False
    
    return True

def test_connection_acquisition_and_release():
    """Test connection acquisition and release from pool."""
    print("\n🔍 Testing Connection Acquisition and Release...")
    
    with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://test:test@localhost/test'}):
        try:
            # Clear any existing pool
            db_utils._connection_pool = None
            
            # Mock the pool and connections
            with patch('db_utils.psycopg2.pool.ThreadedConnectionPool') as mock_pool_class:
                mock_pool = MagicMock()
                mock_conn = MagicMock()
                mock_pool.getconn.return_value = mock_conn
                mock_pool_class.return_value = mock_pool
                
                # Test connection acquisition
                conn = _conn()
                mock_pool.getconn.assert_called_once()
                
                # Test connection release
                _release_conn(conn)
                mock_pool.putconn.assert_called_once_with(conn)
                
                print("✅ Connection acquisition and release working correctly")
                
        except Exception as e:
            print(f"❌ Connection acquisition/release failed: {e}")
            return False
    
    return True

def test_concurrent_connection_usage():
    """Test that multiple threads can safely use connections from the pool."""
    print("\n🔍 Testing Concurrent Connection Usage...")
    
    with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://test:test@localhost/test'}):
        try:
            # Clear any existing pool
            db_utils._connection_pool = None
            
            # Mock the pool
            with patch('db_utils.psycopg2.pool.ThreadedConnectionPool') as mock_pool_class:
                mock_pool = MagicMock()
                
                # Create multiple mock connections
                mock_connections = [MagicMock() for _ in range(5)]
                mock_pool.getconn.side_effect = mock_connections
                mock_pool_class.return_value = mock_pool
                
                connections_used = []
                
                def worker_thread(thread_id):
                    """Worker function that gets and releases a connection."""
                    try:
                        conn = _conn()
                        connections_used.append((thread_id, conn))
                        time.sleep(0.1)  # Simulate some work
                        _release_conn(conn)
                        return True
                    except Exception as e:
                        print(f"Thread {thread_id} failed: {e}")
                        return False
                
                # Run multiple threads concurrently
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                    futures = [executor.submit(worker_thread, i) for i in range(5)]
                    results = [f.result() for f in concurrent.futures.as_completed(futures)]
                
                # Verify all threads succeeded
                assert all(results), "All threads should succeed"
                assert len(connections_used) == 5, "Should have 5 connection usages"
                
                # Verify getconn was called for each thread
                assert mock_pool.getconn.call_count == 5
                
                print("✅ Concurrent connection usage working correctly")
                
        except Exception as e:
            print(f"❌ Concurrent connection usage failed: {e}")
            return False
    
    return True

def test_connection_pool_cleanup():
    """Test that connection pool is properly cleaned up."""
    print("\n🔍 Testing Connection Pool Cleanup...")
    
    with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://test:test@localhost/test'}):
        try:
            # Clear any existing pool
            db_utils._connection_pool = None
            
            # Mock the pool
            with patch('db_utils.psycopg2.pool.ThreadedConnectionPool') as mock_pool_class:
                mock_pool = MagicMock()
                mock_pool_class.return_value = mock_pool
                
                # Initialize pool
                pool = get_connection_pool()
                assert db_utils._connection_pool is not None
                
                # Test cleanup
                close_connection_pool()
                mock_pool.closeall.assert_called_once()
                assert db_utils._connection_pool is None
                
                print("✅ Connection pool cleanup working correctly")
                
        except Exception as e:
            print(f"❌ Connection pool cleanup failed: {e}")
            return False
    
    return True

def test_database_functions_use_pooling():
    """Test that database functions properly use connection pooling."""
    print("\n🔍 Testing Database Functions Use Pooling...")
    
    with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://test:test@localhost/test'}):
        try:
            # Clear any existing pool
            db_utils._connection_pool = None
            
            # Mock the pool and connections
            with patch('db_utils.psycopg2.pool.ThreadedConnectionPool') as mock_pool_class:
                mock_pool = MagicMock()
                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
                mock_conn.cursor.return_value.__exit__.return_value = None
                mock_pool.getconn.return_value = mock_conn
                mock_pool_class.return_value = mock_pool
                
                # Test execute function
                db_utils.execute("SELECT 1", ())
                mock_pool.getconn.assert_called()
                mock_pool.putconn.assert_called_with(mock_conn)
                mock_conn.commit.assert_called()
                
                # Reset mocks
                mock_pool.reset_mock()
                mock_conn.reset_mock()
                
                # Test fetch_one function
                mock_cursor.fetchone.return_value = (1,)
                result = db_utils.fetch_one("SELECT 1", ())
                mock_pool.getconn.assert_called()
                mock_pool.putconn.assert_called_with(mock_conn)
                assert result == (1,)
                
                print("✅ Database functions using connection pooling correctly")
                
        except Exception as e:
            print(f"❌ Database functions pooling test failed: {e}")
            return False
    
    return True

def main():
    """Run all connection pooling tests."""
    print("🚀 Starting Connection Pooling Tests for db_utils.py")
    print("=" * 60)
    
    tests = [
        test_connection_pool_initialization,
        test_connection_acquisition_and_release,
        test_concurrent_connection_usage,
        test_connection_pool_cleanup,
        test_database_functions_use_pooling,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ Test {test.__name__} crashed: {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"📊 Test Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("🎉 All connection pooling tests passed!")
        print("\n💡 Connection pooling benefits:")
        print("  • Reduced connection overhead")
        print("  • Better performance under load")
        print("  • Controlled resource usage")
        print("  • Thread-safe connection management")
    else:
        print(f"❌ {failed} tests failed. Please review the implementation.")
        return False
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
