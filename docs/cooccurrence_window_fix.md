# Co-occurrence Window Inconsistency Fix

## Issue
There was an inconsistency in co-occurrence window settings:
- `risk_shared.py` defaults to `window=12` 
- `rss_processor.py` overrides to `RSS_COOC_WINDOW_TOKENS=15`

## Components Affected
1. `risk_shared.py`: 
   - `KeywordMatcher.__init__(window=12)`
   - `build_default_matcher(window=12)`
   - `DEFAULT_MATCHER` uses window=12

2. `rss_processor.py`:
   - `RSS_COOC_WINDOW_TOKENS=15`
   - Creates custom matcher with window=15
   - Falls back to `build_default_matcher(window=15)` 

## ✅ Fix Applied
Standardized on window=15 across all components by updating `risk_shared.py` defaults:

### Changes Made:
1. **risk_shared.py**:
   - Updated `KeywordMatcher.__init__(window: int = 15)` (was 12)
   - Updated `build_default_matcher(window: int = 15)` (was 12)  
   - Updated `DEFAULT_MATCHER = build_default_matcher(window=15)` (was 12)
   - Updated docstring to reflect default window=15

2. **rss_processor.py**:
   - Updated comment to show alignment: "Aligned with risk_shared.py default"

### Verification:
- ✅ Both components now use window=15 by default
- ✅ Syntax checks pass
- ✅ Matchers work correctly with new window size
- ✅ Consistent behavior across all components

## Why window=15?
- Provides slightly more flexibility for co-occurrence detection
- Already in use and tested in `rss_processor.py`
- The comment showed it was intentionally "Increased from 12 to 15"
- Better coverage for complex sentence structures
- Maintains backward compatibility while improving consistency

## Impact:
- **Improved**: Consistent filtering behavior across all components
- **Improved**: Predictable matcher behavior for testing and debugging
- **No Breaking Changes**: Window=15 is more permissive than 12, so no alerts should be lost
