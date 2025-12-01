"""threat_fusion.py

Unified threat intelligence fusion for Sentinel AI.
Combines RSS alerts + GDELT events + ACLED data + SOCMINT into cohesive threat assessments.
"""

from typing import List, Dict, Optional
from datetime import datetime, timedelta
import logging
from math import radians, cos, sin, asin, sqrt

logger = logging.getLogger("threat_fusion")

class ThreatFusion:
    
    @staticmethod
    def assess_location(lat: float, lon: float, country_code: str = None, 
                       radius_km: int = 100, days: int = 14) -> Dict:
        """
        Unified threat assessment for a location.
        Combines all Sentinel AI intelligence sources:
        - RSS alerts (enriched with LLM analysis)
        - GDELT events (conflict intelligence)
        - ACLED data (if available)
        - SOCMINT signals
        
        Returns structured assessment with risk level, categories, and actionable intel.
        """
        
        # 1. Gather GDELT threats
        gdelt_threats = ThreatFusion._get_gdelt_threats(lat, lon, radius_km, days)
        
        # 2. Gather RSS alerts from your alerts table
        rss_threats = ThreatFusion._get_rss_threats(lat, lon, radius_km, days)
        
        # 3. Get ACLED data if available
        acled_threats = ThreatFusion._get_acled_threats(lat, lon, radius_km, days)
        
        # 4. Get SOCMINT signals if available
        socmint_signals = ThreatFusion._get_socmint_signals(lat, lon, radius_km, days)
        
        # 5. Get country-level summary if country code provided
        country_summary = None
        if country_code:
            from gdelt_query import GDELTQuery
            country_summary = GDELTQuery.get_country_summary(country_code, days=30)
        
        # 6. Deduplicate (same event from multiple sources)
        all_threats = ThreatFusion._deduplicate_threats(
            gdelt_threats, rss_threats, acled_threats
        )
        
        # 7. Score and categorize
        categorized = ThreatFusion._categorize_threats(all_threats)
        
        # 8. Calculate overall risk level
        risk_level = ThreatFusion._calculate_risk_level(
            gdelt_threats, rss_threats, acled_threats, country_summary
        )
        
        # 9. Generate actionable recommendations
        recommendations = ThreatFusion._generate_recommendations(
            risk_level, categorized, country_summary
        )
        
        return {
            'location': {'lat': lat, 'lon': lon, 'country': country_code},
            'assessment_date': datetime.utcnow().isoformat(),
            'period_days': days,
            'radius_km': radius_km,
            'risk_level': risk_level,  # LOW, MODERATE, HIGH, SEVERE
            'country_summary': country_summary,
            'threat_categories': categorized,
            'total_threats': len(all_threats),
            'sources': {
                'gdelt_events': len(gdelt_threats),
                'rss_alerts': len(rss_threats),
                'acled_events': len(acled_threats),
                'socmint_signals': len(socmint_signals)
            },
            'top_threats': all_threats[:10],  # Most severe/recent
            'recommendations': recommendations,
            'verified_by_multiple_sources': len([t for t in all_threats if t.get('source_count', 0) > 1])
        }
    
    @staticmethod
    def _get_gdelt_threats(lat: float, lon: float, radius_km: int, days: int) -> List[Dict]:
        """Fetch GDELT threats near location"""
        try:
            from gdelt_query import GDELTQuery
            return GDELTQuery.get_threats_near_location(lat, lon, radius_km, days)
        except Exception as e:
            logger.error("[threat_fusion] GDELT query failed: %s", e)
            return []
    
    @staticmethod
    def _get_rss_threats(lat: float, lon: float, radius_km: int, days: int) -> List[Dict]:
        """Fetch RSS alerts from Sentinel AI alerts table"""
        try:
            from utils.db_utils import _get_db_connection
            
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            query = """
            SELECT 
                uuid,
                title,
                summary,
                link,
                source,
                published,
                country,
                city,
                latitude,
                longitude,
                category,
                subcategory,
                score,
                label,
                confidence,
                gpt_summary
            FROM alerts
            WHERE 
                latitude IS NOT NULL 
                AND longitude IS NOT NULL
                AND published >= %s
                AND (
                    6371 * acos(
                        cos(radians(%s)) * cos(radians(latitude)) *
                        cos(radians(longitude) - radians(%s)) +
                        sin(radians(%s)) * sin(radians(latitude))
                    )
                ) <= %s
            ORDER BY published DESC
            LIMIT 100
            """
            
            with _get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(query, (cutoff_date, lat, lon, lat, radius_km))
                rows = cur.fetchall()
                
                threats = []
                for row in rows:
                    threats.append({
                        'event_id': row[0],  # uuid
                        'date': row[5].strftime('%Y%m%d') if row[5] else '',  # published
                        'title': row[1],
                        'summary': row[2] or row[15],  # summary or gpt_summary
                        'actor1': row[4],  # source
                        'actor2': '',
                        'country': row[6],
                        'city': row[7],
                        'lat': float(row[8]) if row[8] else 0,
                        'lon': float(row[9]) if row[9] else 0,
                        'category': row[10],
                        'subcategory': row[11],
                        'severity': ThreatFusion._score_to_severity(row[12]),  # score
                        'articles': 1,  # RSS alerts are individual articles
                        'sources': 1,
                        'source_url': row[3],  # link
                        'confidence': row[14],  # confidence
                        'label': row[13],  # label
                        'distance_km': ThreatFusion._haversine_distance(
                            lat, lon, 
                            float(row[8]) if row[8] else 0, 
                            float(row[9]) if row[9] else 0
                        )
                    })
                
                return threats
                
        except Exception as e:
            logger.error("[threat_fusion] RSS query failed: %s", e)
            return []
    
    @staticmethod
    def _score_to_severity(score_str: str) -> float:
        """Convert RSS score (LOW/MEDIUM/HIGH) to numeric severity"""
        if not score_str:
            return 5.0
        score_str = score_str.upper()
        if 'HIGH' in score_str or 'SEVERE' in score_str:
            return 8.0
        elif 'MEDIUM' in score_str or 'MODERATE' in score_str:
            return 5.0
        elif 'LOW' in score_str:
            return 2.0
        return 5.0
    
    @staticmethod
    def _get_acled_threats(lat: float, lon: float, radius_km: int, days: int) -> List[Dict]:
        """Fetch ACLED conflicts near location - placeholder for future implementation"""
        try:
            # TODO: Implement ACLED query when credentials are configured
            # Check if ACLED_ENABLED and credentials exist
            # Query acled_events table if exists
            return []
        except Exception as e:
            logger.error("[threat_fusion] ACLED query failed: %s", e)
            return []
    
    @staticmethod
    def _get_socmint_signals(lat: float, lon: float, radius_km: int, days: int) -> List[Dict]:
        """Fetch SOCMINT signals - placeholder for future implementation"""
        try:
            # TODO: Implement SOCMINT query
            # Query socmint_signals or apify_results table if exists
            return []
        except Exception as e:
            logger.error("[threat_fusion] SOCMINT query failed: %s", e)
            return []
    
    @staticmethod
    def _deduplicate_threats(gdelt: List, rss: List, acled: List) -> List[Dict]:
        """
        Deduplicate threats that appear in multiple sources.
        Merge based on location proximity + date + similar actors/keywords.
        Cross-source verification increases credibility.
        """
        all_threats = []
        seen_signatures = set()
        
        # GDELT events
        for threat in gdelt:
            sig = ThreatFusion._threat_signature(threat, 'gdelt')
            if sig not in seen_signatures:
                threat['source'] = 'GDELT'
                threat['source_count'] = 1
                threat['verified'] = False
                all_threats.append(threat)
                seen_signatures.add(sig)
        
        # RSS alerts (Sentinel AI curated)
        for threat in rss:
            sig = ThreatFusion._threat_signature(threat, 'rss')
            # Check if similar GDELT event exists (same day, ~same location)
            match = ThreatFusion._find_matching_threat(threat, all_threats)
            if match:
                match['source'] = f"{match['source']}, RSS"
                match['source_count'] += 1
                match['verified'] = True  # Cross-source verification
                # Merge RSS enrichments
                if threat.get('summary'):
                    match['rss_summary'] = threat['summary']
                if threat.get('confidence'):
                    match['rss_confidence'] = threat['confidence']
            elif sig not in seen_signatures:
                threat['source'] = 'RSS'
                threat['source_count'] = 1
                threat['verified'] = False
                all_threats.append(threat)
                seen_signatures.add(sig)
        
        # ACLED events
        for threat in acled:
            sig = ThreatFusion._threat_signature(threat, 'acled')
            match = ThreatFusion._find_matching_threat(threat, all_threats)
            if match:
                match['source'] = f"{match['source']}, ACLED"
                match['source_count'] += 1
                match['verified'] = True
            elif sig not in seen_signatures:
                threat['source'] = 'ACLED'
                threat['source_count'] = 1
                threat['verified'] = False
                all_threats.append(threat)
                seen_signatures.add(sig)
        
        # Sort by: verified (multi-source) first, then source count, then severity
        all_threats.sort(
            key=lambda x: (x.get('verified', False), x['source_count'], x.get('severity', 0)), 
            reverse=True
        )
        
        return all_threats
    
    @staticmethod
    def _threat_signature(threat: Dict, source: str) -> str:
        """Generate signature for deduplication"""
        # Basic signature: date + location (rounded) + country
        date = str(threat.get('date', ''))[:8]  # YYYYMMDD
        lat = round(threat.get('lat', 0), 1)
        lon = round(threat.get('lon', 0), 1)
        country = threat.get('country', '')
        return f"{date}_{lat}_{lon}_{country}_{source}"
    
    @staticmethod
    def _find_matching_threat(new_threat: Dict, existing: List[Dict]) -> Optional[Dict]:
        """Find if threat already exists (similar date + location)"""
        new_date = str(new_threat.get('date', ''))[:8]
        new_lat = new_threat.get('lat', 0)
        new_lon = new_threat.get('lon', 0)
        
        for existing_threat in existing:
            exist_date = str(existing_threat.get('date', ''))[:8]
            exist_lat = existing_threat.get('lat', 0)
            exist_lon = existing_threat.get('lon', 0)
            
            # Same day + within 10km
            if exist_date == new_date:
                distance = ThreatFusion._haversine_distance(
                    new_lat, new_lon, exist_lat, exist_lon
                )
                if distance < 10:  # 10km threshold
                    return existing_threat
        
        return None
    
    @staticmethod
    def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two points in km"""
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        km = 6371 * c
        return km
    
    @staticmethod
    def _categorize_threats(threats: List[Dict]) -> Dict:
        """Categorize threats by type using Sentinel AI taxonomy"""
        categories = {
            'civil_unrest': [],
            'terrorism': [],
            'armed_conflict': [],
            'crime': [],
            'political': [],
            'environmental': [],
            'health': [],
            'other': []
        }
        
        for threat in threats:
            # Use Sentinel AI categories if available (from RSS enrichment)
            category = (threat.get('category') or '').lower()
            subcategory = (threat.get('subcategory') or '').lower()
            
            # Also check actors/keywords for GDELT events
            actor1 = (threat.get('actor1') or '').lower()
            actor2 = (threat.get('actor2') or '').lower()
            combined = f"{category} {subcategory} {actor1} {actor2}"
            
            if any(kw in combined for kw in ['protest', 'demonstrat', 'riot', 'unrest', 'strike']):
                categories['civil_unrest'].append(threat)
            elif any(kw in combined for kw in ['terror', 'militant', 'extremist', 'jihadist', 'bomb']):
                categories['terrorism'].append(threat)
            elif any(kw in combined for kw in ['military', 'armed', 'rebel', 'combat', 'war', 'conflict']):
                categories['armed_conflict'].append(threat)
            elif any(kw in combined for kw in ['crime', 'gang', 'kidnap', 'murder', 'cartel', 'violence']):
                categories['crime'].append(threat)
            elif any(kw in combined for kw in ['election', 'government', 'coup', 'political', 'sanction']):
                categories['political'].append(threat)
            elif any(kw in combined for kw in ['disaster', 'earthquake', 'flood', 'hurricane', 'climate']):
                categories['environmental'].append(threat)
            elif any(kw in combined for kw in ['epidemic', 'disease', 'health', 'pandemic', 'outbreak']):
                categories['health'].append(threat)
            else:
                categories['other'].append(threat)
        
        return {k: v for k, v in categories.items() if v}  # Only non-empty categories
    
    @staticmethod
    def _calculate_risk_level(gdelt: List, rss: List, acled: List, 
                             country_summary: Optional[Dict]) -> str:
        """
        Calculate overall risk level: LOW, MODERATE, HIGH, SEVERE
        Based on event count, severity, recency, cross-source verification, and country context.
        """
        total_threats = len(gdelt) + len(rss) + len(acled)
        
        if total_threats == 0:
            return 'LOW'
        
        # Severity scoring (weighted by source)
        avg_severity = 0
        if gdelt:
            avg_severity += sum(t.get('severity', 0) for t in gdelt) / len(gdelt) * 0.5
        if rss:
            avg_severity += sum(t.get('severity', 0) for t in rss) / len(rss) * 0.7  # RSS weighted higher (LLM-enriched)
        if acled:
            avg_severity += sum(t.get('severity', 0) for t in acled) / len(acled) * 0.6
        
        # Country context multiplier
        country_risk_multiplier = 1.0
        if country_summary:
            country_events = country_summary.get('total_events', 0)
            if country_events > 100:
                country_risk_multiplier = 1.5  # High conflict country
            elif country_events > 50:
                country_risk_multiplier = 1.3
            elif country_events > 20:
                country_risk_multiplier = 1.1
        
        # Cross-source verification bonus (more credible)
        verified_count = len([t for t in (gdelt + rss + acled) if len([s for s in (gdelt + rss + acled) if ThreatFusion._are_similar(t, s)]) > 1])
        verification_bonus = min(verified_count * 5, 20)  # Cap at +20
        
        # Weighted risk score
        risk_score = (
            total_threats * 3 + 
            avg_severity * 8 + 
            verification_bonus
        ) * country_risk_multiplier
        
        # Thresholds
        if risk_score > 120:
            return 'SEVERE'
        elif risk_score > 60:
            return 'HIGH'
        elif risk_score > 25:
            return 'MODERATE'
        else:
            return 'LOW'
    
    @staticmethod
    def _are_similar(t1: Dict, t2: Dict) -> bool:
        """Check if two threats are similar (for verification)"""
        if t1.get('event_id') == t2.get('event_id'):
            return False  # Same exact threat
        
        date1 = str(t1.get('date', ''))[:8]
        date2 = str(t2.get('date', ''))[:8]
        if date1 != date2:
            return False
        
        lat1, lon1 = t1.get('lat', 0), t1.get('lon', 0)
        lat2, lon2 = t2.get('lat', 0), t2.get('lon', 0)
        distance = ThreatFusion._haversine_distance(lat1, lon1, lat2, lon2)
        return distance < 10  # Within 10km
    
    @staticmethod
    def _generate_recommendations(risk_level: str, categorized: Dict, 
                                 country_summary: Optional[Dict]) -> List[str]:
        """Generate actionable recommendations based on threat assessment"""
        recommendations = []
        
        if risk_level == 'SEVERE':
            recommendations.append("URGENT: Consider immediate evacuation or shelter-in-place protocols")
            recommendations.append("Monitor all communication channels for official guidance")
            recommendations.append("Ensure emergency supplies are readily available")
        elif risk_level == 'HIGH':
            recommendations.append("Heightened security posture recommended")
            recommendations.append("Avoid non-essential travel to the affected area")
            recommendations.append("Establish emergency contact protocols")
        elif risk_level == 'MODERATE':
            recommendations.append("Exercise increased caution and situational awareness")
            recommendations.append("Monitor local news and official alerts")
            recommendations.append("Review and update contingency plans")
        else:
            recommendations.append("Maintain normal security awareness")
            recommendations.append("Continue routine monitoring of local conditions")
        
        # Category-specific recommendations
        if categorized.get('terrorism'):
            recommendations.append("Terrorism risk: Avoid crowded public spaces and transportation hubs")
        if categorized.get('civil_unrest'):
            recommendations.append("Civil unrest detected: Avoid protest areas and government buildings")
        if categorized.get('armed_conflict'):
            recommendations.append("Armed conflict in region: Limit movement and maintain secure location")
        if categorized.get('crime'):
            recommendations.append("Elevated crime activity: Use secure transportation and avoid isolated areas")
        
        # Country context
        if country_summary and country_summary.get('total_events', 0) > 50:
            recommendations.append(f"Country-wide instability: {country_summary.get('total_events')} conflict events recorded in past 30 days")
        
        return recommendations
