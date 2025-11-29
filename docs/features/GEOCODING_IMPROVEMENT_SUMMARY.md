# Geocoding Improvement Summary

## Current Status (Post Phase 1 & 2)

### Overall Coverage
- **Total alerts**: 1,511
- **With coordinates**: 835 (55.3%)
- **Missing coordinates**: 676 (44.7%)

### Quality Breakdown
- **Tier 1 (High Quality)**: 302 alerts (36.2% of geocoded) ✓ **DISPLAY ON MAP**
  - `coordinates`: 207 (original RSS)
  - `nlp_nominatim`: 78 (Phase 2 NLP extraction)
  - `moderate`: 17 (original moderate confidence)

- **Tier 2 (Medium Quality)**: 277 alerts (33.2% of geocoded) ⚠ **Country centroids only**
  - `country_centroid`: 277 (Phase 1 fallback)

- **Tier 3 (Low/None)**: 932 alerts (remaining) ✗ **SUPPRESS FROM MAP**
  - `unknown`: 892 (250 with coords, 642 missing)
  - `low`: 40 (6 with coords, 34 missing)

## ROOT CAUSE ANALYSIS

### Why Phase 2 Had Low Success (10.3%)

1. **Wrong Tools Used**
   - Phase 2 used standalone Nominatim instead of production infrastructure
   - Did NOT use `location_service_consolidated.py` (250+ known cities)
   - Did NOT use `geocoding_service.py` (Redis + PostgreSQL cache + OpenCage API)
   - Did NOT leverage existing `geocoded_locations` table (250 cached entries)

2. **Production Infrastructure Available But Unused**
   - **OpenCage API**: 2,500 requests/day quota (NOT USED in Phase 2)
   - **Redis caching**: Multi-tier cache system (NOT USED)
   - **PostgreSQL cache**: 250 pre-geocoded locations (NOT USED)
   - **location_keywords.json**: Curated database of conflict zones/major cities (NOT USED)

3. **No Quality Gating**
   - Phase 2 accepted all Nominatim results regardless of confidence
   - No filtering of low-quality guesses
   - Country centroids treated same as precise city coordinates

## SOLUTION: Phase 3 (Production Stack + Quality Gating)

### Phase 3 Improvements

1. **Use Existing Production Infrastructure**
   ```python
   # Phase 3 uses YOUR actual production code:
   from location_service_consolidated import detect_location  # NLP extraction
   from geocoding_service import geocode                       # Multi-tier geocoding
   ```

2. **Multi-Tier Geocoding Stack**
   - **Tier 1**: Redis cache (instant)
   - **Tier 2**: PostgreSQL `geocoded_locations` table (fast)
   - **Tier 3**: Nominatim (free, 1 req/sec)
   - **Tier 4**: OpenCage API (high quality, 2,500/day)

3. **Quality Gating**
   - Minimum confidence threshold (default: 6/10)
   - Reject low-confidence guesses
   - Only accept verifiable locations

4. **Map Display Filtering**
   - New module: `map_quality_filter.py`
   - SQL helper: `get_map_quality_sql_filter()`
   - Only display Tier 1 (high quality) on map
   - Suppress country centroids and low-confidence results

### Installation & Setup

```bash
# Install missing library
pip install opencage

# Set OpenCage API key (if not already set)
export OPENCAGE_API_KEY=your_key_here

# Add to .env.production
echo "OPENCAGE_API_KEY=your_key_here" >> .env.production
```

### Usage

```bash
# Test Phase 3 with production stack
python scripts/phase3_production_geocoding.py --limit 100 --dry-run

# Full run with quality gating (min confidence 6/10)
python scripts/phase3_production_geocoding.py --min-confidence 6

# Check map quality stats
python map_quality_filter.py
```

### Expected Improvements

Based on existing infrastructure:
- **250 cached locations** in PostgreSQL → instant lookups
- **OpenCage API** → higher quality than Nominatim
- **location_keywords.json** → better conflict zone coverage
- **Quality gating** → only reliable coordinates on map

Estimated improvement: **+150-300 high-quality geocodes** (bringing Tier 1 from 302 → 450-600)

## Integration: Map Quality Filtering

### In Map API Endpoints

```python
from map_quality_filter import get_map_quality_sql_filter

# Example: Map alerts endpoint
def get_map_alerts():
    quality_filter = get_map_quality_sql_filter(strict=True, table_alias='a')
    
    query = f"""
        SELECT id, title, latitude, longitude, city, country, score
        FROM alerts a
        WHERE {quality_filter}
          AND score >= 50
          AND published >= NOW() - INTERVAL '30 days'
        ORDER BY score DESC
        LIMIT 1000
    """
    # ... execute and return
```

### Quality Tiers

```python
from map_quality_filter import is_displayable_on_map

for alert in alerts:
    if is_displayable_on_map(alert, strict=True):
        # Display on map with confidence
        render_marker(alert)
    else:
        # Suppress from map, show in list only
        render_list_item(alert)
```

## Action Plan

### Immediate (Required)
1. ✅ Phase 1 complete: Country centroids applied (277 alerts)
2. ✅ Phase 2 complete: Basic NLP geocoding (78 alerts)
3. ✅ Map quality filter created
4. ✅ Map aggregates refreshed
5. ⏳ **Run Phase 3**: Use production stack for remaining 676 alerts

### Next Steps
1. Get/verify OpenCage API key
2. Run Phase 3 with production infrastructure
3. Apply map quality filtering in API endpoints
4. Update map UI to use quality-gated queries

### Long-term (Optional)
- Expand `location_keywords.json` with more cities
- Add spaCy NER for advanced entity extraction
- Implement multilingual location detection
- Manual review queue for stubborn cases

## Files Created/Modified

### New Files
- `scripts/phase1_fix_coordinate_gaps.py` - Country centroid fallback
- `scripts/phase2_nlp_geocoding.py` - Basic NLP + Nominatim
- `scripts/phase3_production_geocoding.py` - **Production stack (RECOMMENDED)**
- `map_quality_filter.py` - Quality gating for map display
- `scripts/refresh_aggregates.py` - Map aggregate builder

### Modified Files
- `db_utils.py` - Added GDELT metadata persistence (fixed syntax)
- `vacuum_only.py` - Production env loading + --full flag

## Summary

**Problem**: Only 36% of geocoded alerts are map-displayable quality.

**Root Cause**: Phase 2 didn't use existing production infrastructure (OpenCage, caching, curated location database).

**Solution**: Phase 3 uses production stack + quality gating to achieve higher coverage with reliable coordinates.

**Impact**: Without quality gating, bad coordinates make intel useless. With gating, map shows only trustworthy locations.
