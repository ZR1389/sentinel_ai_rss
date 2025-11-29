# Keywords Management System

## 🎯 Single Source of Truth: `keywords_loader.py`

The Sentinel AI system now uses a **centralized keywords management system** that consolidates all keyword sources into a single file for easier maintenance and consistency.

## 📁 File Structure

```
├── keywords_loader.py           # 🔥 SINGLE SOURCE OF TRUTH
├── config/threat_keywords.json  # 📊 Data source (JSON)
├── risk_shared.py              # ✅ Imports from keywords_loader
├── threat_scorer.py            # ✅ Imports from keywords_loader
├── rss_processor.py            # ✅ Uses keywords_loader
└── [other modules]             # 🔄 Should import from keywords_loader
```

## 🔧 Usage

### Import Keywords in Your Module

```python
# Import specific keyword sets
from keywords_loader import CATEGORY_KEYWORDS, DOMAIN_KEYWORDS, SEVERE_TERMS

# Import utility functions
from keywords_loader import (
    get_all_keywords,
    get_keywords_by_category,
    get_categories_for_keyword,
    get_translated_keywords
)

# Use in your code
cyber_keywords = get_keywords_by_category("Cyber")
all_keywords = get_all_keywords()
ransomware_categories = get_categories_for_keyword("ransomware")
```

### Available Keyword Sets

```python
# Category-based keywords (for threat categorization)
CATEGORY_KEYWORDS = {
    "Crime": [...],
    "Terrorism": [...], 
    "Civil Unrest": [...],
    "Cyber": [...],
    "Infrastructure": [...],
    "Environmental": [...],
    "Epidemic": [...],
    "Military": [...],
    "Other": []
}

# Domain-based keywords (for impact assessment)
DOMAIN_KEYWORDS = {
    "travel_mobility": [...],
    "cyber_it": [...],
    "physical_safety": [...],
    "infrastructure_utilities": [...],
    # ... 19 total domains
}

# Threat scorer keywords (for severity assessment)
SEVERE_TERMS = [...]      # 198 high-impact keywords
MOBILITY_TERMS = [...]    # 18 mobility/travel keywords  
INFRA_TERMS = [...]       # 17 infrastructure keywords
```

## 🔄 Migration from Old System

| **Before** | **After** | **Status** |
|------------|-----------|------------|
| `risk_shared.py` hard-coded keywords | `keywords_loader import` | ✅ **Updated** |
| `threat_scorer.py` hard-coded keywords | `keywords_loader import` | ✅ **Updated** |
| `rss_processor.py` JSON file loading | `keywords_loader.get_all_keywords()` | ✅ **Updated** |
| Multiple keyword sources | Single source of truth | ✅ **Centralized** |

## ✏️ How to Add/Modify Keywords

### ⚠️ IMPORTANT: Only edit `config/threat_keywords.json`

1. **Add new keywords**: Edit `config/threat_keywords.json`
2. **Restart application**: Keywords are loaded at startup
3. **All modules automatically get updates**: No code changes needed

```json
{
  "keywords": [
    "your_new_keyword_here"
  ],
  "translated": {
    "terrorism": {
      "en": ["your_new_english_term"],
      "es": ["your_new_spanish_term"]
    }
  }
}
```

### 🚨 DO NOT edit keywords in:
- ❌ `risk_shared.py` (now imports from keywords_loader)
- ❌ `threat_scorer.py` (now imports from keywords_loader) 
- ❌ Any other `.py` files (use keywords_loader)

## 🛠 Utility Functions

```python
from keywords_loader import *

# Get all unique keywords across all sources
total_keywords = get_all_keywords()  # 395 unique keywords

# Find keywords by category
crime_words = get_keywords_by_category("Crime")

# Find keywords by domain  
mobility_words = get_keywords_by_domain("travel_mobility")

# Find which categories contain a keyword
categories = get_categories_for_keyword("ransomware")  # ["Cyber"]

# Get translations
spanish_terrorism = get_translated_keywords("terrorism", "es")

# Check keyword coverage
domains = get_domains_for_keyword("airport")  # ["travel_mobility", "legal_regulatory"]
```

## 🔍 Configuration Options

### Environment Variables

```bash
# For rss_processor.py keyword loading
export KEYWORDS_SOURCE="merge"          # Use keywords_loader (default)
export KEYWORDS_SOURCE="json_only"      # Legacy JSON-only mode
export KEYWORDS_SOURCE="risk_only"      # Legacy risk_shared-only mode
export KEYWORDS_SOURCE="centralized"    # Force keywords_loader
```

## 📊 Statistics

- **Total Keywords**: 395 unique terms
- **Categories**: 9 threat categories
- **Domains**: 19 impact domains
- **Languages**: Multi-language support via translations
- **Sources Unified**: 3 → 1 (66% reduction in keyword sources)

## 🧪 Testing

```bash
# Test centralized keywords
python -c "from keywords_loader import *; print(f'Loaded {len(get_all_keywords())} keywords')"

# Test all modules
python -c "
from risk_shared import CATEGORY_KEYWORDS;
from threat_scorer import SEVERE_TERMS;
from keywords_loader import get_all_keywords;
print('✅ All modules using centralized keywords')
"
```

## ⚡ Performance Benefits

1. **Consistency**: All modules use same keyword definitions
2. **Maintainability**: Edit one file (`threat_keywords.json`) to update everywhere
3. **Deduplication**: No duplicate keywords across modules
4. **Extensibility**: Easy to add new categories/domains
5. **Validation**: Built-in utility functions for keyword management

---

## 🔗 Related Files

- `config/threat_keywords.json` - Master keyword data
- `keywords_loader.py` - Centralized keyword loader
- `risk_shared.py` - Threat categorization (uses keywords_loader)
- `threat_scorer.py` - Threat scoring (uses keywords_loader) 
- `rss_processor.py` - RSS processing (uses keywords_loader)
