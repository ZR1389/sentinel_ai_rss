# metrics.py – Enhanced Production Metrics with Real-time Monitoring
from __future__ import annotations
import time
import asyncio
import json
import threading
import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Dict, Callable, Any, List, Optional, Tuple
from functools import wraps
from dataclasses import dataclass, field
from statistics import mean, median
import os
import sqlite3

logger = logging.getLogger("metrics")

@dataclass
class MetricSample:
    """Single metric measurement with metadata"""
    name: str
    value: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    tags: Dict[str, str] = field(default_factory=dict)
    metric_type: str = "gauge"  # gauge, counter, timer, histogram

@dataclass
class AlertThreshold:
    """Alert threshold configuration"""
    metric_name: str
    threshold_value: float
    comparison: str = ">"  # >, <, >=, <=, ==, !=
    window_seconds: int = 300  # 5 minutes default
    alert_message: str = ""

@dataclass
class PerformanceAnalysis:
    """Performance analysis results"""
    metric_name: str
    current_avg: float
    baseline_avg: float
    performance_change_pct: float
    trend: str  # "improving", "degrading", "stable"
    recommendations: List[str]
    severity: str  # "info", "warning", "critical"

class EnhancedMetricsCollector:
    """
    Enhanced metrics collector with real-time monitoring, alerting, 
    performance analysis, and dashboard support
    """
    
    def __init__(self):
        # Core metric storage
        self.counters: Dict[str, int] = defaultdict(int)
        self.timers: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))  # Keep last 1000 samples
        self.gauges: Dict[str, float] = {}
        self.histograms: Dict[str, deque] = defaultdict(lambda: deque(maxlen=10000))  # Keep last 10k samples
        
        # Enhanced monitoring features
        self.samples: List[MetricSample] = []
        self.alert_thresholds: List[AlertThreshold] = []
        self.performance_baselines: Dict[str, float] = {}
        self.metric_metadata: Dict[str, Dict[str, Any]] = {}
        
        # Real-time monitoring
        self._lock = threading.Lock()
        self._monitoring_enabled = True
        self._last_cleanup = datetime.utcnow()
        
        # Performance tracking
        self._performance_window = timedelta(hours=1)
        self._baseline_window = timedelta(days=7)
        
        # Initialize persistent storage
        self._init_storage()
        
        # Load existing baselines
        self._load_baselines()
    
    def _init_storage(self):
        """Initialize SQLite storage for metrics persistence"""
        try:
            self.db_path = "metrics.db"
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS metrics_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    value REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    tags TEXT,
                    metric_type TEXT
                )
                """
            )
            # Create index separately for SQLite compatibility
            try:
                self.conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_metrics_samples_name_ts ON metrics_samples(name, timestamp)"
                )
            except Exception:
                pass

            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS performance_baselines (
                    metric_name TEXT PRIMARY KEY,
                    baseline_value REAL NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self.conn.commit()
        except Exception as e:
            logger.warning(f"Failed to initialize metrics storage: {e}")
            self.conn = None
    
    def _load_baselines(self):
        """Load performance baselines from storage"""
        if not self.conn:
            return
        try:
            cursor = self.conn.execute("SELECT metric_name, baseline_value FROM performance_baselines")
            for row in cursor.fetchall():
                self.performance_baselines[row[0]] = row[1]
        except Exception as e:
            logger.warning(f"Failed to load baselines: {e}")
    
    def increment(self, name: str, value: int = 1, tags: Dict[str, str] = None):
        """Increment counter with enhanced tracking"""
        with self._lock:
            self.counters[name] += value
            self._record_sample(name, float(value), "counter", tags or {})
    
    def timing(self, name: str, duration_ms: float, tags: Dict[str, str] = None):
        """Record timing with enhanced tracking and analysis"""
        with self._lock:
            self.timers[name].append(duration_ms)
            self.histograms[name].append(duration_ms)
            self._record_sample(name, duration_ms, "timer", tags or {})
            self._check_performance_alerts(name, duration_ms)
    
    def gauge(self, name: str, value: float, tags: Dict[str, str] = None):
        """Set gauge value with enhanced tracking"""
        with self._lock:
            self.gauges[name] = value
            self._record_sample(name, value, "gauge", tags or {})
    
    def histogram(self, name: str, value: float, tags: Dict[str, str] = None):
        """Record histogram value for distribution analysis"""
        with self._lock:
            self.histograms[name].append(value)
            self._record_sample(name, value, "histogram", tags or {})
    
    def _record_sample(self, name: str, value: float, metric_type: str, tags: Dict[str, str]):
        """Record metric sample with persistence"""
        sample = MetricSample(name, value, datetime.utcnow(), tags, metric_type)
        self.samples.append(sample)
        
        # Persist to database
        if self.conn:
            try:
                self.conn.execute(
                    "INSERT INTO metrics_samples (name, value, timestamp, tags, metric_type) VALUES (?, ?, ?, ?, ?)",
                    (name, value, sample.timestamp.isoformat(), json.dumps(tags), metric_type)
                )
                self.conn.commit()
            except Exception as e:
                logger.warning(f"Failed to persist metric sample: {e}")
        
        # Cleanup old samples
        self._cleanup_samples()
    
    def _cleanup_samples(self):
        """Remove old samples to prevent memory growth"""
        now = datetime.utcnow()
        if now - self._last_cleanup > timedelta(minutes=10):
            cutoff = now - timedelta(hours=24)  # Keep 24 hours of samples in memory
            self.samples = [s for s in self.samples if s.timestamp > cutoff]
            self._last_cleanup = now
    
    def _check_performance_alerts(self, name: str, value: float):
        """Check if metric value triggers any performance alerts"""
        for threshold in self.alert_thresholds:
            if threshold.metric_name == name:
                self._evaluate_alert_threshold(threshold, value)
    
    def _evaluate_alert_threshold(self, threshold: AlertThreshold, value: float):
        """Evaluate if threshold is breached and trigger alert"""
        breached = False
        
        if threshold.comparison == ">" and value > threshold.threshold_value:
            breached = True
        elif threshold.comparison == "<" and value < threshold.threshold_value:
            breached = True
        elif threshold.comparison == ">=" and value >= threshold.threshold_value:
            breached = True
        elif threshold.comparison == "<=" and value <= threshold.threshold_value:
            breached = True
        elif threshold.comparison == "==" and value == threshold.threshold_value:
            breached = True
        elif threshold.comparison == "!=" and value != threshold.threshold_value:
            breached = True
        
        if breached:
            alert_msg = threshold.alert_message or f"Metric {threshold.metric_name} breached threshold"
            logger.warning(f"[METRIC_ALERT] {alert_msg}: {value} {threshold.comparison} {threshold.threshold_value}")
    
    def add_alert_threshold(self, metric_name: str, threshold_value: float, 
                           comparison: str = ">", window_seconds: int = 300, 
                           alert_message: str = ""):
        """Add performance alert threshold"""
        threshold = AlertThreshold(metric_name, threshold_value, comparison, window_seconds, alert_message)
        self.alert_thresholds.append(threshold)
        logger.info(f"Added alert threshold: {metric_name} {comparison} {threshold_value}")
    
    def set_performance_baseline(self, metric_name: str, baseline_value: float):
        """Set performance baseline for comparison"""
        self.performance_baselines[metric_name] = baseline_value
        
        # Persist baseline
        if self.conn:
            try:
                self.conn.execute(
                    "INSERT OR REPLACE INTO performance_baselines (metric_name, baseline_value, updated_at) VALUES (?, ?, ?)",
                    (metric_name, baseline_value, datetime.utcnow().isoformat())
                )
                self.conn.commit()
            except Exception as e:
                logger.warning(f"Failed to persist baseline: {e}")
    
    def analyze_performance(self, metric_name: str, window_hours: int = 1) -> Optional[PerformanceAnalysis]:
        """Analyze performance against baseline"""
        if metric_name not in self.performance_baselines:
            return None
        
        # Get recent samples
        cutoff = datetime.utcnow() - timedelta(hours=window_hours)
        recent_samples = [s for s in self.samples 
                         if s.name == metric_name and s.timestamp > cutoff and s.metric_type == "timer"]
        
        if not recent_samples:
            return None
        
        current_avg = mean([s.value for s in recent_samples])
        baseline_avg = self.performance_baselines[metric_name]
        change_pct = ((current_avg - baseline_avg) / baseline_avg) * 100 if baseline_avg > 0 else 0
        
        # Determine trend
        if change_pct < -5:
            trend = "improving"
            severity = "info"
        elif change_pct > 20:
            trend = "degrading" 
            severity = "critical"
        elif change_pct > 10:
            trend = "degrading"
            severity = "warning"
        else:
            trend = "stable"
            severity = "info"
        
        # Generate recommendations
        recommendations = []
        if trend == "degrading":
            recommendations.append(f"Performance degraded by {change_pct:.1f}% - investigate recent changes")
            if current_avg > 1000:  # For timing metrics in ms
                recommendations.append("Consider optimization: current average > 1 second")
            recommendations.append("Check database query performance and index usage")
            recommendations.append("Review recent code changes and resource utilization")
        elif trend == "improving":
            recommendations.append(f"Performance improved by {abs(change_pct):.1f}% - good trend")
        
        return PerformanceAnalysis(
            metric_name=metric_name,
            current_avg=current_avg,
            baseline_avg=baseline_avg,
            performance_change_pct=change_pct,
            trend=trend,
            recommendations=recommendations,
            severity=severity
        )
    
    def get_metrics_dashboard_data(self) -> Dict[str, Any]:
        """Get comprehensive metrics data for dashboard display"""
        dashboard_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "summary": {
                "total_counters": len(self.counters),
                "total_timers": len(self.timers),
                "total_gauges": len(self.gauges),
                "active_alerts": len(self.alert_thresholds),
                "samples_collected": len(self.samples)
            },
            "counters": dict(self.counters),
            "gauges": dict(self.gauges),
            "timers": {},
            "performance_analysis": [],
            "alerts": []
        }
        
        # Process timer statistics
        for name, values in self.timers.items():
            if values:
                values_list = list(values)
                dashboard_data["timers"][name] = {
                    "count": len(values_list),
                    "avg_ms": mean(values_list),
                    "min_ms": min(values_list),
                    "max_ms": max(values_list),
                    "median_ms": median(values_list),
                    "p95_ms": self._percentile(values_list, 95),
                    "p99_ms": self._percentile(values_list, 99),
                    "recent_trend": self._calculate_trend(values_list)
                }
        
        # Add performance analyses
        for metric_name in self.performance_baselines:
            analysis = self.analyze_performance(metric_name)
            if analysis:
                dashboard_data["performance_analysis"].append({
                    "metric_name": analysis.metric_name,
                    "current_avg": analysis.current_avg,
                    "baseline_avg": analysis.baseline_avg,
                    "change_pct": analysis.performance_change_pct,
                    "trend": analysis.trend,
                    "severity": analysis.severity,
                    "recommendations": analysis.recommendations
                })
        
        # Add alert status
        for threshold in self.alert_thresholds:
            dashboard_data["alerts"].append({
                "metric_name": threshold.metric_name,
                "threshold_value": threshold.threshold_value,
                "comparison": threshold.comparison,
                "message": threshold.alert_message,
                "window_seconds": threshold.window_seconds
            })
        
        return dashboard_data
    
    def _percentile(self, values: List[float], percentile: int) -> float:
        """Calculate percentile of values"""
        if not values:
            return 0.0
        sorted_values = sorted(values)
        index = int(len(sorted_values) * percentile / 100)
        return sorted_values[min(index, len(sorted_values) - 1)]
    
    def _calculate_trend(self, values: List[float], window: int = 10) -> str:
        """Calculate trend direction for recent values"""
        if len(values) < window:
            return "insufficient_data"
        
        recent = values[-window:]
        older = values[-window*2:-window] if len(values) >= window*2 else values[:-window]
        
        if not older:
            return "insufficient_data"
        
        recent_avg = mean(recent)
        older_avg = mean(older)
        
        change_pct = ((recent_avg - older_avg) / older_avg) * 100 if older_avg > 0 else 0
        
        if change_pct > 5:
            return "increasing"
        elif change_pct < -5:
            return "decreasing"
        else:
            return "stable"
    
    def generate_performance_report(self, hours_back: int = 24) -> Dict[str, Any]:
        """Generate comprehensive performance report"""
        cutoff = datetime.utcnow() - timedelta(hours=hours_back)
        recent_samples = [s for s in self.samples if s.timestamp > cutoff]
        
        report = {
            "report_period": f"Last {hours_back} hours",
            "generated_at": datetime.utcnow().isoformat(),
            "total_samples": len(recent_samples),
            "metrics_summary": {},
            "performance_insights": [],
            "recommendations": []
        }
        
        # Analyze each metric type
        metric_groups = defaultdict(list)
        for sample in recent_samples:
            metric_groups[sample.name].append(sample)
        
        for metric_name, samples in metric_groups.items():
            values = [s.value for s in samples]
            if not values:
                continue
            
            metric_summary = {
                "sample_count": len(values),
                "avg_value": mean(values),
                "min_value": min(values),
                "max_value": max(values),
                "std_dev": self._std_deviation(values),
                "metric_type": samples[0].metric_type
            }
            
            report["metrics_summary"][metric_name] = metric_summary
            
            # Generate insights
            if samples[0].metric_type == "timer":
                if metric_summary["avg_value"] > 1000:
                    report["performance_insights"].append(f"⚠️ {metric_name}: High average response time ({metric_summary['avg_value']:.1f}ms)")
                if metric_summary["max_value"] > 5000:
                    report["performance_insights"].append(f"🔥 {metric_name}: Detected outlier response time ({metric_summary['max_value']:.1f}ms)")
                if metric_summary["std_dev"] > metric_summary["avg_value"]:
                    report["performance_insights"].append(f"📊 {metric_name}: High variance in response times - investigate consistency")
        
        # General recommendations
        report["recommendations"] = [
            "Monitor response time percentiles (P95, P99) for better performance insights",
            "Set up alerting thresholds for critical metrics",
            "Implement performance baselines for trend analysis",
            "Regular review of slow queries and optimization opportunities"
        ]
        
        return report
    
    def _std_deviation(self, values: List[float]) -> float:
        """Calculate standard deviation"""
        if len(values) < 2:
            return 0.0
        avg = mean(values)
        variance = sum((x - avg) ** 2 for x in values) / len(values)
        return variance ** 0.5
    
    def reset_metrics(self, metric_types: List[str] = None):
        """Reset specified metrics or all metrics"""
        with self._lock:
            if not metric_types:
                metric_types = ["counters", "timers", "gauges", "histograms"]
            
            if "counters" in metric_types:
                self.counters.clear()
            if "timers" in metric_types:
                self.timers.clear()
            if "gauges" in metric_types:
                self.gauges.clear()
            if "histograms" in metric_types:
                self.histograms.clear()
            
            logger.info(f"Reset metrics: {metric_types}")

    def timer(self, name: str) -> Callable:
        """Enhanced timer decorator with error handling and tagging"""
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                start = time.perf_counter()
                tags = {"function": func.__name__, "module": func.__module__}
                error_occurred = False
                
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    error_occurred = True
                    tags["error"] = type(e).__name__
                    self.increment(f"{name}.errors", 1, tags)
                    raise
                finally:
                    duration_ms = (time.perf_counter() - start) * 1000
                    if error_occurred:
                        tags["status"] = "error"
                    else:
                        tags["status"] = "success"
                    self.timing(name, duration_ms, tags)
            
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                start = time.perf_counter()
                tags = {"function": func.__name__, "module": func.__module__}
                error_occurred = False
                
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    error_occurred = True
                    tags["error"] = type(e).__name__
                    self.increment(f"{name}.errors", 1, tags)
                    raise
                finally:
                    duration_ms = (time.perf_counter() - start) * 1000
                    if error_occurred:
                        tags["status"] = "error"
                    else:
                        tags["status"] = "success"
                    self.timing(name, duration_ms, tags)
                    
            return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
        return decorator

# Global enhanced metrics instance
METRICS = EnhancedMetricsCollector()

class EnhancedRSSProcessorMetrics:
    """Enhanced RSS Processor metrics with alerting, baselines, and dashboard support."""
    def __init__(self):
        self.collector = METRICS
        self._setup_default_alerts()
        self._setup_default_baselines()

    def _setup_default_alerts(self):
        self.collector.add_alert_threshold("rss.feed_processing_time", 5000, ">", 300, "Feed processing taking too long")
        self.collector.add_alert_threshold("rss.errors.parsing.invalid_feed", 10, ">", 300, "High feed parsing error rate")
        self.collector.add_alert_threshold("rss.database.insert_time", 2000, ">", 300, "Database operations running slow")
        self.collector.add_alert_threshold("rss.llm.openai.call_time", 10000, ">", 300, "LLM API responses taking too long")

    def _setup_default_baselines(self):
        self.collector.set_performance_baseline("rss.feed_processing_time", 2000)
        self.collector.set_performance_baseline("rss.database.insert_time", 500)
        self.collector.set_performance_baseline("rss.llm.openai.call_time", 3000)
        self.collector.set_performance_baseline("rss.location_extraction_time", 1000)

    def record_feed_processing_time(self, duration_seconds: float, feed_name: str = "unknown", success: bool = True):
        tags = {"feed_name": feed_name, "success": str(success).lower()}
        self.collector.timing("rss.feed_processing_time", duration_seconds * 1000, tags)
        if success:
            self.collector.increment("rss.feeds_processed_success", 1, tags)
        else:
            self.collector.increment("rss.feeds_processed_failure", 1, tags)

    def record_location_extraction_time(self, duration_seconds: float, method: str = "unknown", success: bool = True, location_found: bool = False):
        tags = {"method": method, "success": str(success).lower(), "location_found": str(location_found).lower()}
        self.collector.timing(f"rss.location_extraction_time.{method}", duration_seconds * 1000, tags)
        if location_found:
            self.collector.increment(f"rss.location_extraction_success.{method}", 1, tags)
        else:
            self.collector.increment(f"rss.location_extraction_no_result.{method}", 1, tags)

    def record_batch_processing_time(self, duration_seconds: float, batch_size: int = 0, processed_count: int = 0, error_count: int = 0):
        tags = {"batch_size": str(batch_size), "processed_count": str(processed_count), "error_count": str(error_count), "success_rate": str((processed_count / batch_size * 100) if batch_size > 0 else 0)}
        self.collector.timing("rss.batch_processing_time", duration_seconds * 1000, tags)
        self.collector.gauge("rss.last_batch_size", float(batch_size), tags)
        self.collector.gauge("rss.last_batch_success_rate", (processed_count / batch_size * 100) if batch_size > 0 else 0, tags)
        if error_count > 0:
            self.collector.increment("rss.batch_errors", error_count, tags)

    def increment_error_count(self, category: str, error_type: str, error_details: str = "", feed_name: str = "unknown"):
        tags = {"category": category, "error_type": error_type, "feed_name": feed_name, "has_details": str(bool(error_details)).lower()}
        self.collector.increment(f"rss.errors.{category}.{error_type}", 1, tags)
        self.collector.increment("rss.errors.total", 1, tags)
        if error_details:
            self.collector.increment(f"rss.error_patterns.{category}", 1, {"pattern": error_details[:50]})

    def increment_alert_count(self, count: int, alert_type: str = "unknown", severity: str = "info", location: str = "unknown", source_feed: str = "unknown"):
        tags = {"alert_type": alert_type, "severity": severity, "location": location, "source_feed": source_feed}
        self.collector.increment("rss.alerts_processed", count, tags)
        self.collector.increment(f"rss.alerts_by_type.{alert_type}", count, tags)
        self.collector.increment(f"rss.alerts_by_severity.{severity}", count, tags)
        if location != "unknown":
            self.collector.increment(f"rss.alerts_by_location", count, {"location": location})

    def record_database_operation_time(self, duration_seconds: float, operation: str = "unknown", table: str = "unknown", row_count: int = 0, success: bool = True):
        tags = {"operation": operation, "table": table, "success": str(success).lower(), "row_count_range": self._get_row_count_range(row_count)}
        self.collector.timing(f"rss.database.{operation}_time", duration_seconds * 1000, tags)
        if success:
            self.collector.increment(f"rss.database.{operation}_success", 1, tags)
        else:
            self.collector.increment(f"rss.database.{operation}_failure", 1, tags)

    def record_llm_api_call_time(self, duration_seconds: float, provider: str = "unknown", operation: str = "call", success: bool = True, token_count: int = 0, model: str = "unknown"):
        tags = {"provider": provider, "operation": operation, "model": model, "success": str(success).lower(), "token_range": self._get_token_range(token_count)}
        self.collector.timing(f"rss.llm.{provider}.{operation}_time", duration_seconds * 1000, tags)
        if token_count > 0:
            self.collector.histogram(f"rss.llm.{provider}.token_usage", float(token_count), tags)
        if success:
            self.collector.increment(f"rss.llm.{provider}.calls_success", 1, tags)
        else:
            self.collector.increment(f"rss.llm.{provider}.calls_failure", 1, tags)

    def _get_row_count_range(self, row_count: int) -> str:
        if row_count == 0:
            return "zero"
        elif row_count <= 10:
            return "small"
        elif row_count <= 100:
            return "medium"
        elif row_count <= 1000:
            return "large"
        else:
            return "very_large"

    def _get_token_range(self, token_count: int) -> str:
        if token_count == 0:
            return "zero"
        elif token_count <= 100:
            return "small"
        elif token_count <= 1000:
            return "medium"
        elif token_count <= 4000:
            return "large"
        else:
            return "very_large"

    def get_performance_summary(self) -> dict:
        dashboard_data = self.collector.get_metrics_dashboard_data()
        rss_insights = {
            "feed_processing_health": self._analyze_feed_processing_health(),
            "error_rate_analysis": self._analyze_error_rates(),
            "performance_trends": self._analyze_performance_trends(),
            "recommendations": self._generate_recommendations()
        }
        dashboard_data["rss_specific"] = rss_insights
        return dashboard_data

    def _analyze_feed_processing_health(self) -> dict:
        success_count = self.collector.counters.get("rss.feeds_processed_success", 0)
        failure_count = self.collector.counters.get("rss.feeds_processed_failure", 0)
        total_count = success_count + failure_count
        success_rate = (success_count / total_count * 100) if total_count > 0 else 0
        health_status = "healthy"
        if success_rate < 90:
            health_status = "degraded"
        if success_rate < 70:
            health_status = "unhealthy"
        return {"success_count": success_count, "failure_count": failure_count, "success_rate": success_rate, "health_status": health_status}

    def _analyze_error_rates(self) -> dict:
        total_errors = self.collector.counters.get("rss.errors.total", 0)
        total_processed = self.collector.counters.get("rss.feeds_processed_success", 0) + self.collector.counters.get("rss.feeds_processed_failure", 0)
        error_rate = (total_errors / total_processed * 100) if total_processed > 0 else 0
        error_categories = {}
        for metric_name, count in self.collector.counters.items():
            if metric_name.startswith("rss.errors.") and not metric_name.endswith(".total"):
                error_categories[metric_name] = count
        top_errors = sorted(error_categories.items(), key=lambda x: x[1], reverse=True)[:5]
        return {"total_errors": total_errors, "error_rate": error_rate, "top_error_types": [{"type": name, "count": count} for name, count in top_errors]}

    def _analyze_performance_trends(self) -> dict:
        key_metrics = ["rss.feed_processing_time", "rss.database.insert_time", "rss.llm.openai.call_time"]
        trends = {}
        for metric in key_metrics:
            analysis = self.collector.analyze_performance(metric)
            if analysis:
                trends[metric] = {"trend": analysis.trend, "change_pct": analysis.performance_change_pct, "severity": analysis.severity}
        return trends

    def _generate_recommendations(self) -> List[str]:
        recommendations = []
        error_rate = self._analyze_error_rates()["error_rate"]
        if error_rate > 10:
            recommendations.append(f"🚨 High error rate ({error_rate:.1f}%) - investigate error patterns and feeds")
        trends = self._analyze_performance_trends()
        for metric, trend_data in trends.items():
            if trend_data["severity"] == "critical":
                recommendations.append(f"🔥 {metric} performance degraded significantly - immediate optimization needed")
            elif trend_data["severity"] == "warning":
                recommendations.append(f"⚠️ {metric} performance declining - monitor closely")
        if "rss.database.insert_time" in self.collector.timers:
            db_times = list(self.collector.timers["rss.database.insert_time"])
            if db_times and mean(db_times) > 1000:
                recommendations.append("💾 Database operations slow - check indexes and query optimization")
        if not recommendations:
            recommendations.append("✅ All systems operating within normal parameters")
        return recommendations

# Global enhanced RSS metrics instance
RSS_METRICS = EnhancedRSSProcessorMetrics()