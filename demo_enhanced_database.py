#!/usr/bin/env python3
"""
Enhanced Database Operations Demo
================================

This demo showcases the enhanced database operations with comprehensive
logging, performance monitoring, and index optimization for Sentinel AI.

Features demonstrated:
1. Enhanced database logging with performance tracking
2. Query performance monitoring and analysis
3. Database health monitoring
4. Index optimization validation
5. Comprehensive performance reporting
"""

import os
import sys
import time
import logging
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Configure logging to see the enhanced database logging in action
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger("db_demo")

def print_header(title):
    """Print formatted header"""
    print(f"\n{'='*80}")
    print(f"🔧 {title}")
    print(f"{'='*80}")

def print_section(title):
    """Print formatted section"""
    print(f"\n{'📊 ' + title}")
    print(f"{'-'*60}")

def demo_query_sanitization():
    """Demonstrate query sanitization for secure logging"""
    print_section("Query Sanitization Demo")
    
    from db_utils import _sanitize_query_for_log
    
    # Test cases for query sanitization
    test_queries = [
        ("Password Query", "UPDATE users SET password='secret123' WHERE email='user@example.com'"),
        ("Token Query", "SELECT * FROM sessions WHERE token='abc123def456' AND active=true"),
        ("API Key Query", "INSERT INTO api_keys (key) VALUES ('sk_test_123456789')"),
        ("Long Query", "SELECT " + ", ".join([f"column_{i}" for i in range(30)]) + " FROM large_table"),
        ("Safe Query", "SELECT id, name FROM users WHERE active=true"),
    ]
    
    print("🔒 Testing query sanitization for secure logging:")
    for name, query in test_queries:
        sanitized = _sanitize_query_for_log(query, max_length=120)
        print(f"\n   {name}:")
        print(f"     Original: {query[:60]}...")
        print(f"     Sanitized: {sanitized}")
        
        # Verify sensitive data is removed
        if "password" in query.lower() or "token" in query.lower() or "key" in query.lower():
            sensitive_words = ["secret123", "abc123def456", "sk_test_123456789"]
            for word in sensitive_words:
                if word in query and word not in sanitized:
                    print(f"     ✅ Sensitive data '{word}' properly removed")

def demo_performance_monitoring():
    """Demonstrate query performance monitoring"""
    print_section("Query Performance Monitoring Demo")
    
    from db_utils import (
        _log_query_performance, get_query_performance_stats, 
        reset_query_performance_stats
    )
    
    # Reset stats for clean demo
    reset_query_performance_stats()
    
    print("⚡ Simulating various query performance patterns:")
    
    # Simulate different types of queries with various performance characteristics
    query_simulations = [
        ("Fast user lookup", "SELECT id, name FROM users WHERE email=%s", (0.005, 1)),
        ("Alert search", "SELECT * FROM alerts WHERE country=%s AND published > %s", (0.025, 15)),
        ("Bulk data insert", "INSERT INTO raw_alerts (uuid, title, ...) VALUES %s", (0.150, None)),
        ("Complex analytics", "SELECT country, COUNT(*) FROM alerts GROUP BY country", (0.350, 50)),
        ("Slow report query", "SELECT * FROM alerts JOIN raw_alerts ON ... WHERE ...", (1.8, 1000)),
        ("Another user lookup", "SELECT id, name FROM users WHERE email=%s", (0.003, 1)),  # Same query type
        ("Database maintenance", "VACUUM ANALYZE alerts", (2.5, None)),  # Very slow
    ]
    
    for query_name, query, (duration, row_count) in query_simulations:
        print(f"   Executing: {query_name} (Duration: {duration}s, Rows: {row_count})")
        _log_query_performance(query, (), duration, row_count)
        time.sleep(0.1)  # Small delay for realism
    
    print(f"\n📈 Performance Statistics Analysis:")
    stats = get_query_performance_stats()
    summary = stats['summary']
    
    print(f"   Total Queries: {summary['total_queries']}")
    print(f"   Total Duration: {summary['total_duration']:.3f}s")
    print(f"   Average Duration: {summary['average_duration']:.3f}s")
    print(f"   Slow Queries: {summary['slow_queries']} ({summary['slow_query_percentage']:.1f}%)")
    print(f"   Unique Query Types: {summary['query_types']}")
    
    # Show detailed stats for slow queries
    if stats['top_slow_queries']:
        print(f"\n🐌 Top Slow Query Types:")
        for query_hash, query_stats in stats['top_slow_queries'][:3]:
            if query_stats['slow_queries'] > 0:
                print(f"   {query_stats['query_type']} (Hash: {query_hash}):")
                print(f"     Slow queries: {query_stats['slow_queries']}")
                print(f"     Max duration: {query_stats['max_duration']:.3f}s")
                print(f"     Average: {query_stats['avg_duration']:.3f}s")

def demo_database_logging():
    """Demonstrate enhanced database operation logging"""
    print_section("Enhanced Database Logging Demo")
    
    from db_utils import _log_db_operation
    
    print("📝 Testing comprehensive database operation logging:")
    
    # Simulate successful operations
    print("\n   ✅ Successful Operations:")
    _log_db_operation(
        operation_type="FETCH_ALL",
        query="SELECT uuid, title, country FROM alerts WHERE published > %s",
        params=("2025-01-01",),
        duration=0.045,
        row_count=25
    )
    
    _log_db_operation(
        operation_type="EXECUTE",
        query="INSERT INTO user_usage (email, chat_messages_used) VALUES (%s, %s)",
        params=("user@example.com", 5),
        duration=0.008
    )
    
    # Simulate error operations
    print("\n   ❌ Error Operations:")
    _log_db_operation(
        operation_type="FETCH_ONE",
        query="SELECT * FROM non_existent_table WHERE id=%s",
        params=(123,),
        error=Exception("relation 'non_existent_table' does not exist")
    )
    
    _log_db_operation(
        operation_type="EXECUTE",
        query="UPDATE users SET plan=%s WHERE email=%s",
        params=("PREMIUM", "nonexistent@example.com"),
        error=Exception("constraint violation: email not found")
    )

def demo_database_monitoring():
    """Demonstrate database health monitoring"""
    print_section("Database Health Monitoring Demo")
    
    from database_monitor import DatabaseMonitor, DatabaseHealthMetrics
    
    print("🏥 Creating database monitor and simulating health metrics collection:")
    
    monitor = DatabaseMonitor()
    
    # Create sample health metrics to demonstrate monitoring capabilities
    sample_metrics = DatabaseHealthMetrics(
        timestamp=datetime.utcnow(),
        total_connections=15,
        active_connections=8,
        idle_connections=7,
        longest_running_query=45.5,
        database_size="2.3 GB",
        cache_hit_ratio=94.2,
        index_usage_ratio=87.8,
        slow_queries_last_hour=3,
        table_bloat_percentage=8.5,
        vacuum_needed_tables=["alerts", "raw_alerts"],
        health_status="healthy",
        recommendations=[
            "Consider vacuum maintenance for 2 tables with high bloat",
            "Monitor slow queries - 3 detected in last hour"
        ]
    )
    
    # Add to monitor history
    monitor.health_history.append(sample_metrics)
    
    print(f"   Database Status: {sample_metrics.health_status.upper()}")
    print(f"   Total Connections: {sample_metrics.total_connections} (Active: {sample_metrics.active_connections})")
    print(f"   Cache Hit Ratio: {sample_metrics.cache_hit_ratio:.1f}%")
    print(f"   Index Usage: {sample_metrics.index_usage_ratio:.1f}%")
    print(f"   Database Size: {sample_metrics.database_size}")
    print(f"   Table Bloat: {sample_metrics.table_bloat_percentage:.1f}%")
    
    if sample_metrics.recommendations:
        print(f"\n   💡 Recommendations:")
        for i, rec in enumerate(sample_metrics.recommendations, 1):
            print(f"     {i}. {rec}")
    
    # Demonstrate optimization recommendations
    print(f"\n🔍 Testing optimization recommendation logic:")
    
    # Test various scenarios
    scenarios = [
        ("Healthy Database", {
            'total_connections': 10, 'cache_hit_ratio': 96.0, 'index_usage_ratio': 92.0,
            'average_bloat_percentage': 5.0, 'slow_queries_total': 1, 'longest_running_query': 30.0,
            'vacuum_needed_tables': []
        }),
        ("Warning Conditions", {
            'total_connections': 35, 'cache_hit_ratio': 87.0, 'index_usage_ratio': 75.0,
            'average_bloat_percentage': 18.0, 'slow_queries_total': 12, 'longest_running_query': 90.0,
            'vacuum_needed_tables': ['table1', 'table2']
        }),
        ("Critical Issues", {
            'total_connections': 65, 'cache_hit_ratio': 72.0, 'index_usage_ratio': 60.0,
            'average_bloat_percentage': 30.0, 'slow_queries_total': 25, 'longest_running_query': 450.0,
            'vacuum_needed_tables': ['t1', 't2', 't3', 't4', 't5', 't6', 't7']
        })
    ]
    
    for scenario_name, metrics in scenarios:
        recommendations = monitor.get_optimization_recommendations(metrics)
        health_status = monitor.assess_health_status(metrics, recommendations)
        
        status_emoji = {'healthy': '💚', 'warning': '🟡', 'critical': '🔴'}.get(health_status, '❓')
        print(f"\n   {status_emoji} {scenario_name}: {health_status.upper()}")
        print(f"     Recommendations: {len(recommendations)}")
        for rec in recommendations[:2]:  # Show first 2 recommendations
            print(f"       • {rec[:80]}...")

def demo_performance_summary():
    """Demonstrate comprehensive performance summary logging"""
    print_section("Performance Summary Demo")
    
    from db_utils import log_database_performance_summary
    
    print("📊 Generating comprehensive database performance summary:")
    print("   (Check the logs above for detailed performance information)")
    
    # This will use the stats accumulated from previous demos
    log_database_performance_summary()

def demo_index_recommendations():
    """Demonstrate index optimization recommendations"""
    print_section("Index Optimization Recommendations Demo")
    
    print("🔍 Index optimization recommendations:")
    print("   (Note: This demo shows the type of analysis performed)")
    
    # Simulate index analysis results
    index_analysis = [
        {
            'table_name': 'alerts',
            'index_name': 'idx_alerts_published_desc',
            'index_scans': 15420,
            'sequential_scans': 45,
            'efficiency': 'HIGH EFFICIENCY',
            'size': '2.1 MB',
            'recommendation': 'Excellent performance - frequently used'
        },
        {
            'table_name': 'raw_alerts',
            'index_name': 'idx_raw_alerts_country',
            'index_scans': 234,
            'sequential_scans': 1890,
            'efficiency': 'LOW USAGE',
            'size': '890 KB',
            'recommendation': 'Consider composite index with published date'
        },
        {
            'table_name': 'users',
            'index_name': 'idx_users_old_column',
            'index_scans': 0,
            'sequential_scans': 1250,
            'efficiency': 'UNUSED',
            'size': '125 KB',
            'recommendation': 'Consider dropping - no usage detected'
        }
    ]
    
    print("\n   📈 Index Performance Analysis:")
    for idx in index_analysis:
        efficiency_emoji = {
            'HIGH EFFICIENCY': '🟢',
            'LOW USAGE': '🟡',
            'UNUSED': '🔴'
        }.get(idx['efficiency'], '❓')
        
        print(f"   {efficiency_emoji} {idx['table_name']}.{idx['index_name']}:")
        print(f"     Size: {idx['size']}, Scans: {idx['index_scans']}, Efficiency: {idx['efficiency']}")
        print(f"     💡 {idx['recommendation']}")
    
    print(f"\n   📋 Key Index Optimization Principles:")
    principles = [
        "Composite indexes for multi-column WHERE clauses",
        "Descending indexes for ORDER BY ... DESC queries",
        "Partial indexes with WHERE clauses for filtered queries",
        "GIN indexes for JSONB and array columns",
        "Regular analysis of index usage statistics"
    ]
    
    for i, principle in enumerate(principles, 1):
        print(f"     {i}. {principle}")

def demo_real_world_scenarios():
    """Demonstrate real-world database operation scenarios"""
    print_section("Real-World Database Scenarios Demo")
    
    print("🌍 Simulating real-world database operation patterns:")
    
    scenarios = [
        {
            'name': 'Peak Traffic Load',
            'description': 'High concurrent user activity with mixed query types',
            'queries': [
                ('User authentication', 0.008),
                ('Alert dashboard load', 0.045),
                ('Real-time feed update', 0.120),
                ('User authentication', 0.006),
                ('Chat message fetch', 0.025),
                ('Alert search', 0.080),
            ]
        },
        {
            'name': 'Data Processing Pipeline', 
            'description': 'Batch processing of RSS feeds and threat analysis',
            'queries': [
                ('Bulk RSS insert', 1.200),
                ('Threat analysis batch', 0.850),
                ('Location enrichment', 0.450),
                ('Alert categorization', 0.650),
                ('Deduplication process', 0.320),
            ]
        },
        {
            'name': 'Analytics and Reporting',
            'description': 'Complex analytical queries for insights and reports',
            'queries': [
                ('Regional trend analysis', 2.100),
                ('Threat category aggregation', 0.780),
                ('User engagement metrics', 0.340),
                ('System performance stats', 0.180),
            ]
        }
    ]
    
    from db_utils import _log_query_performance
    
    for scenario in scenarios:
        print(f"\n   📊 {scenario['name']}:")
        print(f"     {scenario['description']}")
        
        total_duration = 0
        for query_name, duration in scenario['queries']:
            print(f"     Executing: {query_name} ({duration}s)")
            _log_query_performance(f"-- {query_name}", (), duration, None)
            total_duration += duration
            time.sleep(0.05)  # Brief pause for realism
        
        print(f"     Total scenario duration: {total_duration:.3f}s")

def main():
    """Run comprehensive enhanced database operations demo"""
    
    print_header("Enhanced Database Operations Demo for Sentinel AI")
    print("🚀 Demonstrating comprehensive database logging, monitoring, and optimization")
    print("=" * 80)
    
    try:
        # Run all demo sections
        demo_query_sanitization()
        demo_performance_monitoring()
        demo_database_logging()
        demo_database_monitoring()
        demo_index_recommendations()
        demo_real_world_scenarios()
        demo_performance_summary()
        
        print_header("Demo Summary")
        print("✅ All enhanced database features demonstrated successfully!")
        
        print("\n📋 Key Features Shown:")
        features = [
            "🔒 Query sanitization for secure logging",
            "⚡ Real-time query performance monitoring",
            "📝 Comprehensive database operation logging",
            "🏥 Database health assessment and monitoring", 
            "🔍 Index optimization recommendations",
            "📊 Performance statistics and analysis",
            "🌍 Real-world scenario simulations",
            "💡 Automated optimization recommendations"
        ]
        
        for feature in features:
            print(f"   {feature}")
        
        print(f"\n🎯 Benefits Achieved:")
        benefits = [
            "Enhanced visibility into database performance",
            "Automated detection of slow queries and optimization opportunities",
            "Secure logging that protects sensitive data",
            "Real-time monitoring of database health",
            "Proactive recommendations for performance improvements",
            "Comprehensive audit trail for database operations"
        ]
        
        for benefit in benefits:
            print(f"   • {benefit}")
        
        print(f"\n📚 Next Steps:")
        next_steps = [
            "Apply the database index optimization script",
            "Set up automated database health monitoring",
            "Configure slow query alerting thresholds",
            "Implement regular performance review processes"
        ]
        
        for step in next_steps:
            print(f"   1. {step}")
        
    except Exception as e:
        print(f"❌ Demo failed with error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        print(f"\n🎬 Demo completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()
