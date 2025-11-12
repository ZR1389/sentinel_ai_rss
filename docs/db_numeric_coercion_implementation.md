# Database Numeric Type Coercion Implementation

## Overview
Updated `db_utils.py` to implement comprehensive numeric type coercion and validation for all database operations. This ensures data integrity and prevents silent type conversion errors after the database migration to NUMERIC types.

## Key Changes

### 1. Universal `_coerce_numeric` Function
```python
def _coerce_numeric(value, default, min_val=None, max_val=None):
    """
    Safely coerce to numeric with bounds checking.
    - Handles None values with defaults
    - Converts strings to float
    - Handles NaN values by using defaults
    - Enforces minimum and maximum bounds
    - Falls back to default on conversion errors
    """
```

### 2. Protected Fields in Raw Alerts (`save_raw_alerts_to_db`)
- **Latitude**: Bounded to [-90, 90]
- **Longitude**: Bounded to [-180, 180]

### 3. Protected Fields in Enriched Alerts (`save_alerts_to_db`)
- **score**: Bounded to [0, 100], default 0
- **confidence**: Bounded to [0, 1], default 0.5
- **category_confidence**: Bounded to [0, 1], default 0.5
- **trend_score**: Bounded to [0, 100], default 0
- **future_risk_probability**: Bounded to [0, 1], default 0.25
- **keyword_weight**: Minimum 0, no maximum, default 0
- **incident_count_30d**: Minimum 0, no maximum, default 0
- **recent_count_7d**: Minimum 0, no maximum, default 0
- **baseline_avg_7d**: Minimum 0, no maximum, default 0
- **baseline_ratio**: Minimum 0, no maximum, default 1.0
- **latitude**: Bounded to [-90, 90], default None
- **longitude**: Bounded to [-180, 180], default None

### 4. Protected Fields in Region Trends (`save_region_trend`)
- **incident_count**: Minimum 0, no maximum, default 0

## Validation Features

### Input Type Handling
- ✅ **Numeric values**: Pass through with bounds checking
- ✅ **String numbers**: Convert to float with bounds checking  
- ✅ **Invalid strings**: Use default value
- ✅ **None values**: Use default value
- ✅ **NaN values**: Use default value (special handling)
- ✅ **Out of bounds**: Clamp to min/max

### Bounds Enforcement
- **Scores**: 0-100 scale for threat/trend scores
- **Probabilities**: 0-1 scale for confidence/probability values
- **Geographic**: Valid latitude/longitude ranges
- **Counts**: Non-negative integers for incident counts

## Testing

Comprehensive test suite created (`tests/integration/test_db_numeric_coercion.py`) validates:
- ✅ Basic function behavior with edge cases
- ✅ String-to-numeric conversion
- ✅ Bounds checking and clamping
- ✅ NaN and invalid value handling
- ✅ Realistic alert data scenarios

Additional integration testing (`tests/integration/test_complete_numeric_protection.py`) verifies:
- ✅ End-to-end numeric type safety chain
- ✅ Database migration compatibility
- ✅ Score type safety module integration

## Benefits

### Data Integrity
- Prevents database constraint violations
- Ensures consistent data types across all operations
- Eliminates silent type conversion errors

### Error Prevention
- No more `TypeError` on database inserts
- No more invalid geographic coordinates
- No more out-of-range probability values

### Robustness
- Handles malformed input gracefully
- Provides sensible defaults for missing data
- Maintains system stability under data quality issues

## Production Impact

### Before
```python
# Could cause database errors
alert_data = {"score": "invalid", "confidence": 1.5, "latitude": 999}
save_alerts_to_db([alert_data])  # May fail with type/constraint errors
```

### After
```python
# Safely handled with coercion
alert_data = {"score": "invalid", "confidence": 1.5, "latitude": 999}
save_alerts_to_db([alert_data])  # Success: score=0, confidence=1.0, latitude=90
```

### Performance
- Minimal overhead: Simple float conversion and comparison
- No external dependencies
- Fail-fast on conversion errors

### Monitoring
- All coerced values logged at DEBUG level
- Invalid inputs handled gracefully
- Maintains data flow continuity

## Files Modified
- `/db_utils.py`: Core implementation
- `/tests/integration/test_db_numeric_coercion.py`: Comprehensive validation
- `/tests/integration/test_complete_numeric_protection.py`: End-to-end integration testing

## Integration
- ✅ Compatible with existing database schema
- ✅ Works with migrated NUMERIC columns
- ✅ Backward compatible with current data flows
- ✅ No breaking changes to API

This implementation completes the database type safety layer, ensuring that all numeric data entering the database is properly validated, bounded, and typed correctly.
