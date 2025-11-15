"""
coverage_monitor.py — Geographic Coverage and Data Availability Monitoring

Tracks:
- Geographic coverage by country/region
- Alert data volume and freshness
- Location extraction success rates
- Advisory gating frequency
- Data quality metrics
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from threading import Lock
import json

logger = logging.getLogger(__name__)

# ========== Data Classes ==========

@dataclass
class GeographicCoverage:
    """Track coverage by location"""
    country: str
    region: Optional[str] = None
    alert_count_7d: int = 0
    alert_count_30d: int = 0
    last_alert_timestamp: Optional[float] = None
    confidence_avg: float = 0.0
    sources_count: int = 0
    
    def is_stale(self, max_age_hours: int = 24) -> bool:
        """Check if coverage is stale"""
        if not self.last_alert_timestamp:
            return True
        age_hours = (time.time() - self.last_alert_timestamp) / 3600
        return age_hours > max_age_hours
    
    def is_sparse(self, min_alerts_7d: int = 5) -> bool:
        """Check if coverage is sparse"""
        return self.alert_count_7d < min_alerts_7d


@dataclass
class LocationExtractionMetrics:
    """Track location extraction performance"""
    total_queries: int = 0
    successful_extractions: int = 0
    spacy_successes: int = 0
    regex_successes: int = 0
    fallback_successes: int = 0
    extraction_failures: int = 0
    
    def success_rate(self) -> float:
        if self.total_queries == 0:
            return 0.0
        return self.successful_extractions / self.total_queries


@dataclass
class AdvisoryGatingMetrics:
    """Track advisory gating frequency and reasons"""
    total_attempts: int = 0
    gated_location_mismatch: int = 0
    gated_low_confidence: int = 0
    gated_insufficient_data: int = 0
    generated_success: int = 0
    
    def gating_rate(self) -> float:
        if self.total_attempts == 0:
            return 0.0
        total_gated = self.gated_location_mismatch + self.gated_low_confidence + self.gated_insufficient_data
        return total_gated / self.total_attempts


@dataclass
class CoverageMonitorState:
    """Complete monitoring state"""
    geographic_coverage: Dict[str, GeographicCoverage] = field(default_factory=dict)
    location_extraction: LocationExtractionMetrics = field(default_factory=LocationExtractionMetrics)
    advisory_gating: AdvisoryGatingMetrics = field(default_factory=AdvisoryGatingMetrics)
    last_updated: float = field(default_factory=time.time)


# ========== Coverage Monitor ==========

class CoverageMonitor:
    """
    Production-grade coverage monitoring with thread safety.
    
    Tracks:
    - Geographic coverage gaps
    - Location extraction performance  
    - Advisory gating statistics
    - Data quality trends
    """
    
    def __init__(self):
        self._state = CoverageMonitorState()
        self._lock = Lock()
        logger.info("[CoverageMonitor] Initialized")
    
    # ===== Geographic Coverage =====
    
    def record_alert(
        self,
        country: str,
        city: Optional[str] = None,
        region: Optional[str] = None,
        confidence: float = 0.0,
        source_count: int = 1,
    ):
        """Record an alert for geographic coverage tracking"""
        with self._lock:
            key = f"{country}:{region or 'unknown'}"
            
            if key not in self._state.geographic_coverage:
                self._state.geographic_coverage[key] = GeographicCoverage(
                    country=country,
                    region=region,
                )
            
            cov = self._state.geographic_coverage[key]
            cov.alert_count_7d += 1
            cov.alert_count_30d += 1
            cov.last_alert_timestamp = time.time()
            
            # Update rolling average confidence
            if cov.alert_count_7d == 1:
                cov.confidence_avg = confidence
            else:
                # Exponential moving average
                cov.confidence_avg = 0.9 * cov.confidence_avg + 0.1 * confidence
            
            cov.sources_count = max(cov.sources_count, source_count)
            
            self._state.last_updated = time.time()
    
    def get_coverage_gaps(
        self,
        min_alerts_7d: int = 5,
        max_age_hours: int = 24,
    ) -> List[Dict[str, Any]]:
        """Identify geographic coverage gaps"""
        with self._lock:
            gaps = []
            
            for key, cov in self._state.geographic_coverage.items():
                issues = []
                
                if cov.is_stale(max_age_hours):
                    issues.append("stale")
                if cov.is_sparse(min_alerts_7d):
                    issues.append("sparse")
                
                if issues:
                    gaps.append({
                        "country": cov.country,
                        "region": cov.region,
                        "issues": issues,
                        "alert_count_7d": cov.alert_count_7d,
                        "last_alert_age_hours": (time.time() - (cov.last_alert_timestamp or 0)) / 3600,
                        "confidence_avg": round(cov.confidence_avg, 2),
                    })
            
            return sorted(gaps, key=lambda x: x["alert_count_7d"])
    
    def get_covered_locations(self) -> List[Dict[str, Any]]:
        """Get list of well-covered locations"""
        with self._lock:
            covered = []
            
            for key, cov in self._state.geographic_coverage.items():
                if not cov.is_stale(24) and not cov.is_sparse(5):
                    covered.append({
                        "country": cov.country,
                        "region": cov.region,
                        "alert_count_7d": cov.alert_count_7d,
                        "alert_count_30d": cov.alert_count_30d,
                        "confidence_avg": round(cov.confidence_avg, 2),
                        "sources_count": cov.sources_count,
                    })
            
            return sorted(covered, key=lambda x: x["alert_count_7d"], reverse=True)
    
    # ===== Location Extraction =====
    
    def record_location_extraction(
        self,
        success: bool,
        method: Optional[str] = None,
    ):
        """Record location extraction attempt"""
        with self._lock:
            self._state.location_extraction.total_queries += 1
            
            if success:
                self._state.location_extraction.successful_extractions += 1
                
                if method == "spacy":
                    self._state.location_extraction.spacy_successes += 1
                elif method == "regex":
                    self._state.location_extraction.regex_successes += 1
                elif method == "fallback":
                    self._state.location_extraction.fallback_successes += 1
            else:
                self._state.location_extraction.extraction_failures += 1
            
            self._state.last_updated = time.time()
    
    def get_location_extraction_stats(self) -> Dict[str, Any]:
        """Get location extraction statistics"""
        with self._lock:
            metrics = self._state.location_extraction
            return {
                "total_queries": metrics.total_queries,
                "successful_extractions": metrics.successful_extractions,
                "extraction_failures": metrics.extraction_failures,
                "success_rate": round(metrics.success_rate() * 100, 2),
                "method_breakdown": {
                    "spacy": metrics.spacy_successes,
                    "regex": metrics.regex_successes,
                    "fallback": metrics.fallback_successes,
                },
            }
    
    # ===== Advisory Gating =====
    
    def record_advisory_attempt(
        self,
        generated: bool,
        gate_reason: Optional[str] = None,
    ):
        """Record advisory generation attempt"""
        with self._lock:
            self._state.advisory_gating.total_attempts += 1
            
            if generated:
                self._state.advisory_gating.generated_success += 1
            elif gate_reason:
                if "location" in gate_reason.lower() or "mismatch" in gate_reason.lower():
                    self._state.advisory_gating.gated_location_mismatch += 1
                elif "confidence" in gate_reason.lower():
                    self._state.advisory_gating.gated_low_confidence += 1
                elif "data" in gate_reason.lower() or "insufficient" in gate_reason.lower():
                    self._state.advisory_gating.gated_insufficient_data += 1
            
            self._state.last_updated = time.time()
    
    def get_advisory_gating_stats(self) -> Dict[str, Any]:
        """Get advisory gating statistics"""
        with self._lock:
            metrics = self._state.advisory_gating
            return {
                "total_attempts": metrics.total_attempts,
                "generated_success": metrics.generated_success,
                "gated_location_mismatch": metrics.gated_location_mismatch,
                "gated_low_confidence": metrics.gated_low_confidence,
                "gated_insufficient_data": metrics.gated_insufficient_data,
                "gating_rate": round(metrics.gating_rate() * 100, 2),
                "success_rate": round((metrics.generated_success / max(1, metrics.total_attempts)) * 100, 2),
            }
    
    # ===== Comprehensive Reports =====
    
    def get_comprehensive_report(self) -> Dict[str, Any]:
        """Get complete monitoring report"""
        # Get data without holding lock to avoid deadlock
        covered_locs = self.get_covered_locations()
        coverage_gaps = self.get_coverage_gaps()
        loc_stats = self.get_location_extraction_stats()
        gate_stats = self.get_advisory_gating_stats()
        
        with self._lock:
            return {
                "timestamp": datetime.now().isoformat(),
                "last_updated": datetime.fromtimestamp(self._state.last_updated).isoformat(),
                "geographic_coverage": {
                    "total_locations": len(self._state.geographic_coverage),
                    "covered_locations": len(covered_locs),
                    "coverage_gaps": len(coverage_gaps),
                    "gaps_detail": coverage_gaps[:10],  # Top 10 gaps
                },
                "location_extraction": loc_stats,
                "advisory_gating": gate_stats,
            }
    
    def log_summary(self):
        """Log monitoring summary"""
        report = self.get_comprehensive_report()
        
        logger.info("="*60)
        logger.info("[CoverageMonitor] MONITORING SUMMARY")
        logger.info("="*60)
        
        # Geographic Coverage
        geo = report["geographic_coverage"]
        logger.info(f"Geographic Coverage: {geo['covered_locations']}/{geo['total_locations']} locations well-covered")
        logger.info(f"  Coverage Gaps: {geo['coverage_gaps']} locations")
        
        if geo["gaps_detail"]:
            logger.info("  Top Gaps:")
            for gap in geo["gaps_detail"][:5]:
                logger.info(f"    - {gap['country']} ({gap['region'] or 'unknown'}): {gap['issues']} - {gap['alert_count_7d']} alerts/7d")
        
        # Location Extraction
        loc = report["location_extraction"]
        logger.info(f"Location Extraction: {loc['success_rate']}% success rate")
        logger.info(f"  Total queries: {loc['total_queries']}")
        logger.info(f"  Method breakdown: spaCy={loc['method_breakdown']['spacy']}, regex={loc['method_breakdown']['regex']}, fallback={loc['method_breakdown']['fallback']}")
        
        # Advisory Gating
        gate = report["advisory_gating"]
        logger.info(f"Advisory Gating: {gate['gating_rate']}% gated, {gate['success_rate']}% generated")
        logger.info(f"  Total attempts: {gate['total_attempts']}")
        logger.info(f"  Gate reasons: location={gate['gated_location_mismatch']}, confidence={gate['gated_low_confidence']}, data={gate['gated_insufficient_data']}")
        
        logger.info("="*60)
    
    def reset_metrics(self):
        """Reset all metrics (for testing or periodic reporting)"""
        with self._lock:
            self._state = CoverageMonitorState()
            logger.info("[CoverageMonitor] Metrics reset")
    
    def export_to_json(self) -> str:
        """Export metrics to JSON"""
        report = self.get_comprehensive_report()
        return json.dumps(report, indent=2)


# ========== Global Instance ==========

_coverage_monitor = None

def get_coverage_monitor() -> CoverageMonitor:
    """Get global coverage monitor instance"""
    global _coverage_monitor
    if _coverage_monitor is None:
        _coverage_monitor = CoverageMonitor()
    return _coverage_monitor
