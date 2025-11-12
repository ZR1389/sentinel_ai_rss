#!/usr/bin/env python3
"""
Database Performance Monitoring and Logging Utility
===================================================

This utility provides comprehensive database performance monitoring,
logging, and optimization recommendations for Sentinel AI.

Features:
1. Real-time query performance monitoring
2. Slow query detection and analysis
3. Index usage statistics
4. Database health monitoring
5. Automated optimization recommendations
"""

import os
import sys
import time
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db_utils import (
    fetch_all, fetch_one, execute,
    get_query_performance_stats,
    log_database_performance_summary,
    reset_query_performance_stats
)

logger = logging.getLogger("db_monitor")

@dataclass
class DatabaseHealthMetrics:
    """Database health metrics data structure"""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    total_connections: int = 0
    active_connections: int = 0
    idle_connections: int = 0
    longest_running_query: float = 0.0
    database_size: str = ""
    cache_hit_ratio: float = 0.0
    index_usage_ratio: float = 0.0
    slow_queries_last_hour: int = 0
    table_bloat_percentage: float = 0.0
    vacuum_needed_tables: List[str] = field(default_factory=list)
    health_status: str = "unknown"  # healthy, warning, critical
    recommendations: List[str] = field(default_factory=list)

class DatabaseMonitor:
    """Comprehensive database monitoring and optimization utility"""
    
    def __init__(self):
        self.monitor_start_time = datetime.utcnow()
        self.health_history = []
        self.max_history_size = 1000
        
    def collect_connection_metrics(self) -> Dict[str, Any]:
        """Collect database connection metrics"""
        try:
            query = """
            SELECT 
                COUNT(*) as total_connections,
                COUNT(*) FILTER (WHERE state = 'active') as active_connections,
                COUNT(*) FILTER (WHERE state = 'idle') as idle_connections,
                COUNT(*) FILTER (WHERE state = 'idle in transaction') as idle_in_transaction,
                MAX(EXTRACT(EPOCH FROM (NOW() - query_start))) as longest_running_query
            FROM pg_stat_activity 
            WHERE datname = current_database()
        """
            
            result = fetch_one(query)
            if result:
                return {
                    'total_connections': result[0] or 0,
                    'active_connections': result[1] or 0,
                    'idle_connections': result[2] or 0,
                    'idle_in_transaction': result[3] or 0,
                    'longest_running_query': result[4] or 0.0
                }
            return {}
            
        except Exception as e:
            logger.error(f"Failed to collect connection metrics: {e}")
            return {}
    
    def collect_cache_metrics(self) -> Dict[str, Any]:
        """Collect database cache hit ratio and performance metrics"""
        try:
            # Cache hit ratio
            cache_query = """
            SELECT 
                ROUND(
                    100.0 * sum(blks_hit) / NULLIF(sum(blks_hit + blks_read), 0), 2
                ) as cache_hit_ratio
            FROM pg_stat_database
            WHERE datname = current_database()
            """
            
            cache_result = fetch_one(cache_query)
            cache_hit_ratio = cache_result[0] if cache_result and cache_result[0] else 0.0
            
            # Index usage ratio
            index_query = """
            SELECT 
                ROUND(
                    100.0 * sum(idx_scan) / NULLIF(sum(idx_scan + seq_scan), 0), 2
                ) as index_usage_ratio
            FROM pg_stat_user_tables
            """
            
            index_result = fetch_one(index_query)
            index_usage_ratio = index_result[0] if index_result and index_result[0] else 0.0
            
            return {
                'cache_hit_ratio': cache_hit_ratio,
                'index_usage_ratio': index_usage_ratio
            }
            
        except Exception as e:
            logger.error(f"Failed to collect cache metrics: {e}")
            return {'cache_hit_ratio': 0.0, 'index_usage_ratio': 0.0}
    
    def collect_database_size_metrics(self) -> Dict[str, Any]:
        """Collect database size and storage metrics"""
        try:
            size_query = """
            SELECT 
                pg_size_pretty(pg_database_size(current_database())) as database_size,
                pg_database_size(current_database()) as database_size_bytes
            """
            
            result = fetch_one(size_query)
            if result:
                return {
                    'database_size': result[0],
                    'database_size_bytes': result[1]
                }
            return {'database_size': 'Unknown', 'database_size_bytes': 0}
            
        except Exception as e:
            logger.error(f"Failed to collect database size metrics: {e}")
            return {'database_size': 'Error', 'database_size_bytes': 0}
    
    def collect_table_bloat_metrics(self) -> Dict[str, Any]:
        """Collect table bloat and maintenance metrics"""
        try:
            bloat_query = """
            SELECT 
                schemaname,
                tablename,
                n_live_tup,
                n_dead_tup,
                CASE 
                    WHEN n_live_tup = 0 THEN 0 
                    ELSE ROUND((n_dead_tup::float / n_live_tup) * 100, 2) 
                END as dead_row_percentage,
                last_vacuum,
                last_autovacuum
            FROM pg_stat_user_tables
            WHERE n_live_tup > 0
            ORDER BY dead_row_percentage DESC NULLS LAST
            """
            
            results = fetch_all(bloat_query)
            
            # Calculate average bloat and identify tables needing vacuum
            total_bloat = 0
            vacuum_needed = []
            table_count = 0
            
            for row in results:
                if row['dead_row_percentage'] is not None:
                    total_bloat += row['dead_row_percentage']
                    table_count += 1
                    
                    # Tables with >20% dead rows need vacuum
                    if row['dead_row_percentage'] > 20:
                        vacuum_needed.append(f"{row['tablename']} ({row['dead_row_percentage']}% bloat)")
            
            avg_bloat = total_bloat / table_count if table_count > 0 else 0
            
            return {
                'average_bloat_percentage': avg_bloat,
                'vacuum_needed_tables': vacuum_needed,
                'table_details': results[:10]  # Top 10 most bloated tables
            }
            
        except Exception as e:
            logger.error(f"Failed to collect table bloat metrics: {e}")
            return {
                'average_bloat_percentage': 0.0,
                'vacuum_needed_tables': [],
                'table_details': []
            }
    
    def collect_slow_query_metrics(self) -> Dict[str, Any]:
        """Collect slow query statistics"""
        try:
            # Get query stats from our enhanced logging
            stats = get_query_performance_stats()
            
            # Count slow queries in the last hour (this is approximate based on our in-memory stats)
            slow_queries_count = stats['summary']['slow_queries']
            
            return {
                'slow_queries_total': slow_queries_count,
                'slow_query_percentage': stats['summary']['slow_query_percentage'],
                'total_queries': stats['summary']['total_queries'],
                'average_duration': stats['summary']['average_duration']
            }
            
        except Exception as e:
            logger.error(f"Failed to collect slow query metrics: {e}")
            return {
                'slow_queries_total': 0,
                'slow_query_percentage': 0.0,
                'total_queries': 0,
                'average_duration': 0.0
            }
    
    def get_optimization_recommendations(self, metrics: Dict[str, Any]) -> List[str]:
        """Generate optimization recommendations based on metrics"""
        recommendations = []
        
        # Connection recommendations
        if metrics.get('total_connections', 0) > 50:
            recommendations.append("Consider implementing connection pooling - high connection count detected")
        
        if metrics.get('idle_in_transaction', 0) > 5:
            recommendations.append("Review application code for unclosed transactions - high idle-in-transaction count")
        
        # Cache recommendations
        cache_hit_ratio = metrics.get('cache_hit_ratio', 0)
        if cache_hit_ratio < 90:
            recommendations.append(f"Poor cache hit ratio ({cache_hit_ratio}%) - consider increasing shared_buffers")
        elif cache_hit_ratio < 95:
            recommendations.append(f"Cache hit ratio could be improved ({cache_hit_ratio}%) - monitor memory usage")
        
        # Index recommendations
        index_usage_ratio = metrics.get('index_usage_ratio', 0)
        if index_usage_ratio < 80:
            recommendations.append(f"Low index usage ratio ({index_usage_ratio}%) - review query patterns and add missing indexes")
        
        # Vacuum recommendations
        avg_bloat = metrics.get('average_bloat_percentage', 0)
        if avg_bloat > 15:
            recommendations.append(f"High table bloat ({avg_bloat:.1f}%) - schedule vacuum maintenance")
        
        vacuum_needed = metrics.get('vacuum_needed_tables', [])
        if len(vacuum_needed) > 0:
            recommendations.append(f"Immediate vacuum needed for {len(vacuum_needed)} tables")
        
        # Query performance recommendations
        slow_queries = metrics.get('slow_queries_total', 0)
        if slow_queries > 10:
            recommendations.append(f"High number of slow queries ({slow_queries}) - review and optimize query patterns")
        
        # Long-running query recommendations
        longest_query = metrics.get('longest_running_query', 0)
        if longest_query > 300:  # 5 minutes
            recommendations.append(f"Very long-running query detected ({longest_query:.1f}s) - investigate potential locks")
        elif longest_query > 60:  # 1 minute
            recommendations.append(f"Long-running query detected ({longest_query:.1f}s) - monitor for performance issues")
        
        return recommendations
    
    def assess_health_status(self, metrics: Dict[str, Any], recommendations: List[str]) -> str:
        """Assess overall database health status"""
        critical_issues = 0
        warning_issues = 0
        
        # Critical conditions
        if metrics.get('cache_hit_ratio', 100) < 80:
            critical_issues += 1
        if metrics.get('average_bloat_percentage', 0) > 25:
            critical_issues += 1
        if metrics.get('longest_running_query', 0) > 600:  # 10 minutes
            critical_issues += 1
        if len(metrics.get('vacuum_needed_tables', [])) > 5:
            critical_issues += 1
        
        # Warning conditions
        if metrics.get('cache_hit_ratio', 100) < 90:
            warning_issues += 1
        if metrics.get('index_usage_ratio', 100) < 80:
            warning_issues += 1
        if metrics.get('average_bloat_percentage', 0) > 15:
            warning_issues += 1
        if metrics.get('slow_queries_total', 0) > 10:
            warning_issues += 1
        
        if critical_issues > 0:
            return "critical"
        elif warning_issues > 2:
            return "warning"
        else:
            return "healthy"
    
    def collect_comprehensive_metrics(self) -> DatabaseHealthMetrics:
        """Collect all database health metrics"""
        logger.info("Collecting comprehensive database metrics...")
        
        # Collect all metric categories
        connection_metrics = self.collect_connection_metrics()
        cache_metrics = self.collect_cache_metrics()
        size_metrics = self.collect_database_size_metrics()
        bloat_metrics = self.collect_table_bloat_metrics()
        query_metrics = self.collect_slow_query_metrics()
        
        # Combine all metrics
        all_metrics = {
            **connection_metrics,
            **cache_metrics,
            **size_metrics,
            **bloat_metrics,
            **query_metrics
        }
        
        # Generate recommendations
        recommendations = self.get_optimization_recommendations(all_metrics)
        
        # Assess health status
        health_status = self.assess_health_status(all_metrics, recommendations)
        
        # Create health metrics object
        health_metrics = DatabaseHealthMetrics(
            timestamp=datetime.utcnow(),
            total_connections=all_metrics.get('total_connections', 0),
            active_connections=all_metrics.get('active_connections', 0),
            idle_connections=all_metrics.get('idle_connections', 0),
            longest_running_query=all_metrics.get('longest_running_query', 0.0),
            database_size=all_metrics.get('database_size', 'Unknown'),
            cache_hit_ratio=all_metrics.get('cache_hit_ratio', 0.0),
            index_usage_ratio=all_metrics.get('index_usage_ratio', 0.0),
            slow_queries_last_hour=all_metrics.get('slow_queries_total', 0),
            table_bloat_percentage=all_metrics.get('average_bloat_percentage', 0.0),
            vacuum_needed_tables=all_metrics.get('vacuum_needed_tables', []),
            health_status=health_status,
            recommendations=recommendations
        )
        
        # Store in history
        self.health_history.append(health_metrics)
        
        # Keep history size manageable
        if len(self.health_history) > self.max_history_size:
            self.health_history = self.health_history[-self.max_history_size:]
        
        return health_metrics
    
    def log_health_summary(self, metrics: DatabaseHealthMetrics):
        """Log comprehensive database health summary"""
        status_emoji = {
            'healthy': '💚',
            'warning': '🟡', 
            'critical': '🔴'
        }
        
        logger.info("=" * 80)
        logger.info("📊 DATABASE HEALTH MONITORING SUMMARY")
        logger.info("=" * 80)
        logger.info(f"{status_emoji.get(metrics.health_status, '❓')} Overall Status: {metrics.health_status.upper()}")
        logger.info(f"📅 Timestamp: {metrics.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("")
        
        logger.info("🔗 Connection Metrics:")
        logger.info(f"   Total Connections: {metrics.total_connections}")
        logger.info(f"   Active: {metrics.active_connections}")
        logger.info(f"   Idle: {metrics.idle_connections}")
        logger.info(f"   Longest Running Query: {metrics.longest_running_query:.2f}s")
        logger.info("")
        
        logger.info("⚡ Performance Metrics:")
        logger.info(f"   Cache Hit Ratio: {metrics.cache_hit_ratio:.1f}%")
        logger.info(f"   Index Usage Ratio: {metrics.index_usage_ratio:.1f}%")
        logger.info(f"   Slow Queries: {metrics.slow_queries_last_hour}")
        logger.info(f"   Table Bloat: {metrics.table_bloat_percentage:.1f}%")
        logger.info("")
        
        logger.info("💾 Storage Metrics:")
        logger.info(f"   Database Size: {metrics.database_size}")
        if metrics.vacuum_needed_tables:
            logger.info(f"   Tables Needing Vacuum: {len(metrics.vacuum_needed_tables)}")
        logger.info("")
        
        if metrics.recommendations:
            logger.warning("⚠️  Optimization Recommendations:")
            for i, rec in enumerate(metrics.recommendations, 1):
                logger.warning(f"   {i}. {rec}")
            logger.info("")
        else:
            logger.info("✅ No optimization recommendations at this time")
            logger.info("")
        
        logger.info("=" * 80)
    
    def generate_health_report(self, hours: int = 24) -> Dict[str, Any]:
        """Generate comprehensive health report for the specified time period"""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        
        # Filter history for the specified period
        recent_metrics = [
            m for m in self.health_history 
            if m.timestamp >= cutoff_time
        ]
        
        if not recent_metrics:
            return {
                'error': 'No metrics available for the specified time period',
                'period_hours': hours
            }
        
        # Calculate trends and averages
        avg_cache_hit = sum(m.cache_hit_ratio for m in recent_metrics) / len(recent_metrics)
        avg_index_usage = sum(m.index_usage_ratio for m in recent_metrics) / len(recent_metrics)
        avg_bloat = sum(m.table_bloat_percentage for m in recent_metrics) / len(recent_metrics)
        
        total_slow_queries = sum(m.slow_queries_last_hour for m in recent_metrics)
        max_connections = max(m.total_connections for m in recent_metrics)
        
        # Health status distribution
        status_counts = {'healthy': 0, 'warning': 0, 'critical': 0}
        for m in recent_metrics:
            status_counts[m.health_status] += 1
        
        # Most common recommendations
        all_recommendations = []
        for m in recent_metrics:
            all_recommendations.extend(m.recommendations)
        
        recommendation_counts = {}
        for rec in all_recommendations:
            recommendation_counts[rec] = recommendation_counts.get(rec, 0) + 1
        
        top_recommendations = sorted(
            recommendation_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )[:5]
        
        return {
            'report_period': f'{hours} hours',
            'metrics_collected': len(recent_metrics),
            'current_status': recent_metrics[-1].health_status if recent_metrics else 'unknown',
            'averages': {
                'cache_hit_ratio': avg_cache_hit,
                'index_usage_ratio': avg_index_usage,
                'table_bloat_percentage': avg_bloat
            },
            'totals': {
                'slow_queries': total_slow_queries,
                'max_connections': max_connections
            },
            'health_distribution': status_counts,
            'top_recommendations': top_recommendations,
            'latest_metrics': recent_metrics[-1].__dict__ if recent_metrics else None
        }

def run_database_monitoring_check():
    """Run a comprehensive database monitoring check"""
    monitor = DatabaseMonitor()
    
    try:
        print("🔍 Starting Database Health Check...")
        
        # Collect metrics
        health_metrics = monitor.collect_comprehensive_metrics()
        
        # Log summary
        monitor.log_health_summary(health_metrics)
        
        # Also log query performance summary
        log_database_performance_summary()
        
        return health_metrics
        
    except Exception as e:
        logger.error(f"Database monitoring check failed: {e}")
        raise

def run_index_analysis():
    """Run index usage analysis and recommendations"""
    try:
        print("📊 Analyzing Index Usage...")
        
        # Get index usage statistics
        index_query = """
        SELECT 
            schemaname,
            tablename,
            indexname,
            pg_size_pretty(pg_relation_size(indexrelid)) as index_size,
            idx_scan as index_scans,
            seq_scan as sequential_scans,
            CASE 
                WHEN idx_scan = 0 AND seq_scan > 100 THEN 'UNUSED - Consider dropping'
                WHEN idx_scan < 10 AND seq_scan > 1000 THEN 'LOW USAGE'
                WHEN idx_scan > 1000 AND seq_scan < 100 THEN 'HIGH EFFICIENCY' 
                ELSE 'NORMAL'
            END as efficiency_rating
        FROM pg_stat_user_indexes pui
        JOIN pg_stat_user_tables put ON pui.schemaname = put.schemaname AND pui.tablename = put.tablename
        WHERE pui.schemaname = 'public'
        ORDER BY put.seq_scan DESC, pui.idx_scan ASC
        """
        
        results = fetch_all(index_query)
        
        logger.info("=" * 80)
        logger.info("📊 INDEX USAGE ANALYSIS")
        logger.info("=" * 80)
        
        if results:
            for row in results[:20]:  # Top 20
                logger.info(
                    f"Table: {row['tablename']:<15} Index: {row['indexname']:<30} "
                    f"Size: {row['index_size']:<8} Scans: {row['index_scans']:<6} "
                    f"Rating: {row['efficiency_rating']}"
                )
        
        # Find tables with high sequential scans
        high_seq_scan_query = """
        SELECT tablename, seq_scan, idx_scan, n_live_tup
        FROM pg_stat_user_tables
        WHERE seq_scan > 100 AND schemaname = 'public'
        ORDER BY seq_scan DESC
        LIMIT 10
        """
        
        seq_scan_results = fetch_all(high_seq_scan_query)
        
        logger.info("")
        logger.info("⚠️  Tables with High Sequential Scans (May Need Indexes):")
        for row in seq_scan_results:
            logger.warning(
                f"   {row['tablename']}: {row['seq_scan']} seq scans, "
                f"{row['idx_scan']} index scans, {row['n_live_tup']} rows"
            )
        
        logger.info("=" * 80)
        
        return results
        
    except Exception as e:
        logger.error(f"Index analysis failed: {e}")
        raise

def main():
    """Main function for database monitoring utility"""
    
    print("🚀 Sentinel AI Database Monitoring Utility")
    print("=" * 80)
    
    try:
        # Run comprehensive health check
        health_metrics = run_database_monitoring_check()
        
        print(f"\n📈 Health Check Complete - Status: {health_metrics.health_status.upper()}")
        
        # Run index analysis
        print("\n" + "=" * 80)
        index_results = run_index_analysis()
        
        print(f"\n📊 Index Analysis Complete - Analyzed {len(index_results)} indexes")
        
        # Generate summary report
        monitor = DatabaseMonitor()
        monitor.health_history = [health_metrics]  # Add current metrics
        report = monitor.generate_health_report(hours=1)
        
        print("\n" + "=" * 80)
        print("📋 FINAL SUMMARY")
        print("=" * 80)
        print(f"Database Status: {report['current_status'].upper()}")
        print(f"Cache Hit Ratio: {report['averages']['cache_hit_ratio']:.1f}%")
        print(f"Index Usage: {report['averages']['index_usage_ratio']:.1f}%")
        
        if report['top_recommendations']:
            print("\n💡 Top Recommendations:")
            for rec, count in report['top_recommendations'][:3]:
                print(f"   • {rec}")
        
        print("\n✅ Database monitoring complete!")
        
    except Exception as e:
        print(f"❌ Database monitoring failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
