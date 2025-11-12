"""
Comprehensive Test Suite for Enhanced Database Operations
========================================================

This test suite validates:
1. Enhanced database logging and performance monitoring
2. Database operation performance tracking
3. Query performance statistics and analysis
4. Index optimization validation
5. Database health monitoring
"""

import pytest
import time
import os
import sys
import logging
from unittest.mock import patch, MagicMock
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# Import enhanced database functions
from db_utils import (
    execute, fetch_one, fetch_all, execute_batch,
    get_query_performance_stats, log_database_performance_summary,
    reset_query_performance_stats, _log_query_performance,
    _log_db_operation, _sanitize_query_for_log
)

# Import database monitor
from database_monitor import DatabaseMonitor, DatabaseHealthMetrics

# Configure test logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("test_db_operations")


class TestEnhancedDatabaseLogging:
    """Test enhanced database operation logging"""
    
    def test_query_sanitization(self):
        """Test query sanitization for logging"""
        # Test password sanitization
        query_with_password = "UPDATE users SET password='secret123' WHERE id=1"
        sanitized = _sanitize_query_for_log(query_with_password)
        assert "secret123" not in sanitized
        assert "password=***" in sanitized
        
        # Test token sanitization  
        query_with_token = "SELECT * FROM sessions WHERE token='abc123def' AND active=true"
        sanitized = _sanitize_query_for_log(query_with_token)
        assert "abc123def" not in sanitized
        
        # Test long query truncation
        long_query = "SELECT " + ", ".join([f"col_{i}" for i in range(50)]) + " FROM table"
        sanitized = _sanitize_query_for_log(long_query, max_length=100)
        assert len(sanitized) <= 103  # 100 + "..."
        assert sanitized.endswith("...")
    
    def test_query_performance_tracking(self):
        """Test query performance monitoring"""
        # Reset stats for clean test
        reset_query_performance_stats()
        
        # Simulate query execution with performance logging
        test_query = "SELECT * FROM test_table WHERE id = %s"
        test_params = (1,)
        duration = 0.15
        
        _log_query_performance(test_query, test_params, duration, row_count=1)
        
        # Get statistics
        stats = get_query_performance_stats()
        
        # Verify statistics were recorded
        assert stats['summary']['total_queries'] == 1
        assert stats['summary']['total_duration'] == duration
        assert stats['summary']['average_duration'] == duration
        assert len(stats['detailed_stats']) == 1
        
        # Test slow query detection
        slow_duration = 2.0  # Above threshold
        _log_query_performance(test_query, test_params, slow_duration, row_count=5)
        
        stats = get_query_performance_stats()
        assert stats['summary']['slow_queries'] == 1
        assert stats['summary']['total_queries'] == 2
    
    @patch('db_utils._get_db_connection')
    def test_execute_with_logging(self, mock_conn):
        """Test execute function with comprehensive logging"""
        # Mock database connection
        mock_cursor = MagicMock()
        mock_connection = MagicMock()
        mock_connection.__enter__ = MagicMock(return_value=mock_connection)
        mock_connection.__exit__ = MagicMock(return_value=None)
        mock_connection.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_connection.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_conn.return_value = mock_connection
        
        # Reset stats
        reset_query_performance_stats()
        
        # Test successful execution
        test_query = "INSERT INTO test_table (name) VALUES (%s)"
        test_params = ("test_value",)
        
        execute(test_query, test_params)
        
        # Verify cursor was called correctly
        mock_cursor.execute.assert_called_once_with(test_query, test_params)
        
        # Verify performance stats were recorded
        stats = get_query_performance_stats()
        assert stats['summary']['total_queries'] == 1
    
    @patch('db_utils._get_db_connection')
    def test_fetch_one_with_logging(self, mock_conn):
        """Test fetch_one function with comprehensive logging"""
        # Mock database connection and result
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ("test_result", 123)
        mock_connection = MagicMock()
        mock_connection.__enter__ = MagicMock(return_value=mock_connection)
        mock_connection.__exit__ = MagicMock(return_value=None)
        mock_connection.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_connection.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_conn.return_value = mock_connection
        
        # Reset stats
        reset_query_performance_stats()
        
        # Test successful fetch
        test_query = "SELECT name, id FROM test_table WHERE id = %s"
        test_params = (1,)
        
        result = fetch_one(test_query, test_params)
        
        # Verify result
        assert result == ("test_result", 123)
        
        # Verify cursor was called correctly
        mock_cursor.execute.assert_called_once_with(test_query, test_params)
        mock_cursor.fetchone.assert_called_once()
        
        # Verify performance stats were recorded
        stats = get_query_performance_stats()
        assert stats['summary']['total_queries'] == 1
    
    @patch('db_utils._get_db_connection')
    def test_fetch_all_with_logging(self, mock_conn):
        """Test fetch_all function with comprehensive logging"""
        # Mock database connection with RealDictCursor
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {'id': 1, 'name': 'test1'},
            {'id': 2, 'name': 'test2'}
        ]
        mock_connection = MagicMock()
        mock_connection.__enter__ = MagicMock(return_value=mock_connection)
        mock_connection.__exit__ = MagicMock(return_value=None)
        mock_connection.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_connection.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_conn.return_value = mock_connection
        
        # Reset stats
        reset_query_performance_stats()
        
        # Test successful fetch_all
        test_query = "SELECT * FROM test_table WHERE active = %s"
        test_params = (True,)
        
        result = fetch_all(test_query, test_params)
        
        # Verify result
        assert len(result) == 2
        assert result[0]['name'] == 'test1'
        
        # Verify performance stats were recorded
        stats = get_query_performance_stats()
        assert stats['summary']['total_queries'] == 1
    
    def test_performance_stats_aggregation(self):
        """Test query performance statistics aggregation"""
        reset_query_performance_stats()
        
        # Simulate multiple queries
        queries = [
            ("SELECT * FROM users", (), 0.05, 10),
            ("SELECT * FROM alerts", (), 0.15, 50),
            ("SELECT * FROM users", (), 0.03, 8),  # Same query again
            ("INSERT INTO logs", (), 1.5, None),  # Slow query
        ]
        
        for query, params, duration, row_count in queries:
            _log_query_performance(query, params, duration, row_count)
        
        stats = get_query_performance_stats()
        
        # Verify aggregated statistics
        assert stats['summary']['total_queries'] == 4
        assert stats['summary']['slow_queries'] == 1  # One query over threshold
        assert len(stats['detailed_stats']) == 3  # 3 unique query signatures
        
        # Verify slow query detection
        assert stats['summary']['slow_query_percentage'] == 25.0  # 1 out of 4
    
    def test_database_operation_logging(self, caplog):
        """Test comprehensive database operation logging"""
        with caplog.at_level(logging.INFO):
            # Test successful operation logging
            _log_db_operation(
                operation_type="TEST_OPERATION",
                query="SELECT * FROM test_table",
                params=(),
                duration=0.05,
                row_count=10
            )
            
            # Check that log contains expected information
            assert "DB_SUCCESS" in caplog.text
            assert "TEST_OPERATION" in caplog.text
            assert "0.050s" in caplog.text
            assert "Rows: 10" in caplog.text
        
        caplog.clear()
        
        with caplog.at_level(logging.ERROR):
            # Test error operation logging
            test_error = Exception("Test database error")
            _log_db_operation(
                operation_type="ERROR_OPERATION", 
                query="INVALID SQL",
                params=(),
                error=test_error
            )
            
            # Check that error log contains expected information
            assert "DB_ERROR" in caplog.text
            assert "ERROR_OPERATION" in caplog.text
            assert "Test database error" in caplog.text


class TestDatabaseMonitor:
    """Test database monitoring functionality"""
    
    def test_database_health_metrics_creation(self):
        """Test DatabaseHealthMetrics data structure"""
        metrics = DatabaseHealthMetrics(
            total_connections=10,
            active_connections=5,
            cache_hit_ratio=95.5,
            health_status="healthy"
        )
        
        assert metrics.total_connections == 10
        assert metrics.active_connections == 5
        assert metrics.cache_hit_ratio == 95.5
        assert metrics.health_status == "healthy"
        assert isinstance(metrics.timestamp, datetime)
    
    def test_database_monitor_initialization(self):
        """Test DatabaseMonitor initialization"""
        monitor = DatabaseMonitor()
        
        assert isinstance(monitor.monitor_start_time, datetime)
        assert monitor.health_history == []
        assert monitor.max_history_size == 1000
    
    @patch('database_monitor.fetch_one')
    def test_connection_metrics_collection(self, mock_fetch_one):
        """Test collection of database connection metrics"""
        # Mock database response
        mock_fetch_one.return_value = (25, 5, 15, 2, 45.5)
        
        monitor = DatabaseMonitor()
        metrics = monitor.collect_connection_metrics()
        
        assert metrics['total_connections'] == 25
        assert metrics['active_connections'] == 5
        assert metrics['idle_connections'] == 15
        assert metrics['idle_in_transaction'] == 2
        assert metrics['longest_running_query'] == 45.5
    
    @patch('database_monitor.fetch_one')
    def test_cache_metrics_collection(self, mock_fetch_one):
        """Test collection of database cache metrics"""
        # Mock database responses for cache and index queries
        mock_fetch_one.side_effect = [(95.5,), (87.3,)]
        
        monitor = DatabaseMonitor()
        metrics = monitor.collect_cache_metrics()
        
        assert metrics['cache_hit_ratio'] == 95.5
        assert metrics['index_usage_ratio'] == 87.3
    
    def test_optimization_recommendations(self):
        """Test generation of optimization recommendations"""
        monitor = DatabaseMonitor()
        
        # Test metrics that should generate recommendations
        test_metrics = {
            'total_connections': 60,  # High connection count
            'cache_hit_ratio': 75.0,  # Poor cache hit ratio
            'index_usage_ratio': 65.0,  # Low index usage
            'average_bloat_percentage': 25.0,  # High bloat
            'slow_queries_total': 15,  # Many slow queries
            'longest_running_query': 180.0,  # Long running query
            'vacuum_needed_tables': ['table1', 'table2', 'table3', 'table4', 'table5', 'table6']
        }
        
        recommendations = monitor.get_optimization_recommendations(test_metrics)
        
        # Verify recommendations are generated
        assert len(recommendations) > 0
        
        # Check for specific recommendation types
        rec_text = ' '.join(recommendations)
        assert 'connection pooling' in rec_text  # High connections
        assert 'cache hit ratio' in rec_text  # Poor cache
        assert 'index usage' in rec_text  # Low index usage
        assert 'table bloat' in rec_text  # High bloat
        assert 'slow queries' in rec_text  # Many slow queries
    
    def test_health_status_assessment(self):
        """Test health status assessment logic"""
        monitor = DatabaseMonitor()
        
        # Test healthy status
        healthy_metrics = {
            'cache_hit_ratio': 96.0,
            'index_usage_ratio': 90.0,
            'average_bloat_percentage': 5.0,
            'longest_running_query': 30.0,
            'vacuum_needed_tables': []
        }
        status = monitor.assess_health_status(healthy_metrics, [])
        assert status == "healthy"
        
        # Test warning status
        warning_metrics = {
            'cache_hit_ratio': 85.0,  # Below 90
            'index_usage_ratio': 75.0,  # Below 80
            'average_bloat_percentage': 18.0,  # Above 15
            'slow_queries_total': 12,  # Above 10
            'longest_running_query': 45.0,
            'vacuum_needed_tables': []
        }
        status = monitor.assess_health_status(warning_metrics, [])
        assert status == "warning"
        
        # Test critical status
        critical_metrics = {
            'cache_hit_ratio': 75.0,  # Below 80 (critical)
            'index_usage_ratio': 60.0,
            'average_bloat_percentage': 30.0,  # Above 25 (critical)
            'longest_running_query': 700.0,  # Above 600 (critical)
            'vacuum_needed_tables': ['t1', 't2', 't3', 't4', 't5', 't6']  # >5 tables
        }
        status = monitor.assess_health_status(critical_metrics, [])
        assert status == "critical"
    
    @patch.multiple(
        'database_monitor.DatabaseMonitor',
        collect_connection_metrics=MagicMock(return_value={'total_connections': 10, 'active_connections': 5, 'idle_connections': 5, 'longest_running_query': 30.0}),
        collect_cache_metrics=MagicMock(return_value={'cache_hit_ratio': 95.0, 'index_usage_ratio': 88.0}),
        collect_database_size_metrics=MagicMock(return_value={'database_size': '1.2 GB', 'database_size_bytes': 1200000000}),
        collect_table_bloat_metrics=MagicMock(return_value={'average_bloat_percentage': 8.0, 'vacuum_needed_tables': []}),
        collect_slow_query_metrics=MagicMock(return_value={'slow_queries_total': 2, 'slow_query_percentage': 1.0, 'total_queries': 200, 'average_duration': 0.05})
    )
    def test_comprehensive_metrics_collection(self):
        """Test comprehensive metrics collection"""
        monitor = DatabaseMonitor()
        metrics = monitor.collect_comprehensive_metrics()
        
        # Verify metrics object
        assert isinstance(metrics, DatabaseHealthMetrics)
        assert metrics.total_connections == 10
        assert metrics.cache_hit_ratio == 95.0
        assert metrics.health_status in ['healthy', 'warning', 'critical']
        
        # Verify metrics were stored in history
        assert len(monitor.health_history) == 1
        assert monitor.health_history[0] == metrics
    
    def test_health_report_generation(self):
        """Test health report generation"""
        monitor = DatabaseMonitor()
        
        # Create sample health metrics
        sample_metrics = [
            DatabaseHealthMetrics(
                timestamp=datetime.utcnow(),
                total_connections=10,
                cache_hit_ratio=95.0,
                index_usage_ratio=88.0,
                health_status="healthy",
                recommendations=["Sample recommendation"]
            ),
            DatabaseHealthMetrics(
                timestamp=datetime.utcnow(),
                total_connections=15,
                cache_hit_ratio=92.0,
                index_usage_ratio=85.0,
                health_status="warning",
                recommendations=["Another recommendation", "Sample recommendation"]
            )
        ]
        
        monitor.health_history = sample_metrics
        
        # Generate report
        report = monitor.generate_health_report(hours=24)
        
        # Verify report structure
        assert 'report_period' in report
        assert 'metrics_collected' in report
        assert 'current_status' in report
        assert 'averages' in report
        assert 'health_distribution' in report
        assert 'top_recommendations' in report
        
        # Verify report content
        assert report['metrics_collected'] == 2
        assert report['current_status'] == "warning"
        assert report['averages']['cache_hit_ratio'] == 93.5  # Average of 95.0 and 92.0
        assert report['health_distribution']['healthy'] == 1
        assert report['health_distribution']['warning'] == 1


class TestDatabaseIntegration:
    """Test database operations integration"""
    
    @patch('db_utils._get_db_connection')
    def test_batch_execution_logging(self, mock_conn):
        """Test batch execution with logging"""
        # Mock database connection
        mock_cursor = MagicMock()
        mock_connection = MagicMock()
        mock_connection.__enter__ = MagicMock(return_value=mock_connection)
        mock_connection.__exit__ = MagicMock(return_value=None)
        mock_connection.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_connection.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_conn.return_value = mock_connection
        
        # Reset stats
        reset_query_performance_stats()
        
        # Test batch execution
        test_query = "INSERT INTO test_table (name, value) VALUES (%s, %s)"
        test_params_list = [
            ("name1", "value1"),
            ("name2", "value2"),
            ("name3", "value3")
        ]
        
        affected_rows = execute_batch(test_query, test_params_list)
        
        # Verify return value
        assert affected_rows == 3
        
        # Verify performance stats were recorded
        stats = get_query_performance_stats()
        assert stats['summary']['total_queries'] == 1
    
    def test_performance_summary_logging(self, caplog):
        """Test performance summary logging"""
        # Add some test data to stats
        reset_query_performance_stats()
        _log_query_performance("SELECT * FROM test", (), 0.05, 10)
        _log_query_performance("INSERT INTO test", (), 1.2, None)  # Slow query
        
        with caplog.at_level(logging.INFO):
            log_database_performance_summary()
            
            # Check that summary contains expected information
            assert "DATABASE PERFORMANCE SUMMARY" in caplog.text
            assert "Total Queries:" in caplog.text
            assert "Slow Queries:" in caplog.text
            assert "Average Duration:" in caplog.text


class TestDatabasePerformanceValidation:
    """Test database performance validation"""
    
    def test_query_performance_threshold_validation(self):
        """Test that slow query thresholds are working correctly"""
        # Test queries at various performance levels
        reset_query_performance_stats()
        
        # Fast query (below threshold)
        _log_query_performance("SELECT id FROM users", (), 0.5, 1)
        
        # Slow query (above threshold)
        _log_query_performance("SELECT * FROM large_table", (), 2.0, 1000)
        
        # Get stats
        stats = get_query_performance_stats()
        
        # Verify slow query detection
        assert stats['summary']['total_queries'] == 2
        assert stats['summary']['slow_queries'] == 1
        assert stats['summary']['slow_query_percentage'] == 50.0
    
    def test_memory_efficiency_of_stats_tracking(self):
        """Test that stats tracking doesn't consume excessive memory"""
        reset_query_performance_stats()
        
        # Simulate many queries
        for i in range(1000):
            query = f"SELECT * FROM table_{i % 10}"  # 10 unique queries
            _log_query_performance(query, (), 0.01, 1)
        
        stats = get_query_performance_stats()
        
        # Should have tracked stats efficiently
        assert stats['summary']['total_queries'] == 1000
        assert len(stats['detailed_stats']) == 10  # Only 10 unique query signatures
        
        # Memory usage should be reasonable
        import sys
        stats_size = sys.getsizeof(stats)
        assert stats_size < 100000  # Less than 100KB for tracking


if __name__ == "__main__":
    """Run comprehensive database operation tests"""
    
    print("🧪 Running Enhanced Database Operations Tests")
    print("=" * 80)
    
    # Run pytest with verbose output
    pytest.main([
        __file__,
        "-v",
        "--tb=short",
        "--no-header",
        "-q"
    ])
    
    print("\n" + "=" * 80)
    print("✅ Enhanced database operations tests completed!")
    
    # Also run a quick integration demo
    print("\n🔧 Running Integration Demo...")
    
    try:
        # Test basic functionality
        reset_query_performance_stats()
        
        # Simulate some database operations
        _log_query_performance("SELECT * FROM alerts", (), 0.05, 10)
        _log_query_performance("INSERT INTO logs", (), 1.5, None)  # Slow query
        _log_query_performance("SELECT * FROM users", (), 0.02, 5)
        
        stats = get_query_performance_stats()
        
        print(f"📊 Performance Stats: {stats['summary']['total_queries']} queries")
        print(f"⚡ Average Duration: {stats['summary']['average_duration']:.3f}s")
        print(f"🐌 Slow Queries: {stats['summary']['slow_queries']} ({stats['summary']['slow_query_percentage']:.1f}%)")
        
        # Test database monitor
        monitor = DatabaseMonitor()
        sample_metrics = DatabaseHealthMetrics(
            total_connections=10,
            cache_hit_ratio=95.0,
            health_status="healthy",
            recommendations=[]
        )
        
        print(f"🏥 Database Health: {sample_metrics.health_status}")
        print(f"📈 Cache Hit Ratio: {sample_metrics.cache_hit_ratio}%")
        
        print("✅ Integration demo successful!")
        
    except Exception as e:
        print(f"❌ Integration demo failed: {e}")
        raise
