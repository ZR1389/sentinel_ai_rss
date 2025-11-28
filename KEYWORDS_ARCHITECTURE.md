# Keywords Architecture - Source of Truth Documentation

**Date**: 2025-11-28  
**Status**: ✅ Clarified and Documented  
**Purpose**: Define single source of truth for all keyword management

---

## 🎯 Current State: SYMLINK ARCHITECTURE (CORRECT)

You have a **clean symlink architecture** where `config/` contains symlinks to `config_data/`:

### Threat Keywords:
- ✅ `config_data/threat_keywords.json` - **39,638 bytes** - 261 base keywords - **SOURCE OF TRUTH**
- 🔗 `config/threat_keywords.json` → **symlink** to `../config_data/threat_keywords.json`

### Location Keywords:
- ✅ `config_data/location_keywords.json` - **51,468 bytes** - 339 cities, 224 countries - **SOURCE OF TRUTH**
- 🔗 `config/location_keywords.json` → **symlink** to `../config_data/location_keywords.json`

**Architecture**: ✅ **CORRECT** - No duplicates, clean symlink structure

---

## 📋 Single Source of Truth

### **PRIMARY (Canonical) - Edit These**:
```
config_data/
├── threat_keywords.json     ← SINGLE SOURCE OF TRUTH for threat keywords
├── location_keywords.json   ← SINGLE SOURCE OF TRUTH for location keywords
├── plans.py                 ← User plans configuration
└── risk_profiles.json       ← Risk profile definitions
```

### **SYMLINKS (For Backward Compatibility)**:
```
config/
├── threat_keywords.json     → ../config_data/threat_keywords.json
└── location_keywords.json   → ../config_data/location_keywords.json
```

**Purpose**: The `config/` directory provides backward compatibility for code that expects keywords in `config/` while the actual data lives in `config_data/`.

---

## 🔍 How Keywords Are Loaded

### 1. **Threat Keywords** (`keywords_loader.py`)

**Loading Priority**:
```python
possible_paths = [
    "config/threat_keywords.json",              # ← Symlink to config_data/
    "threat_keywords.json",
    "<script_dir>/config/threat_keywords.json", # ← Symlink to config_data/
    "<script_dir>/threat_keywords.json"
]
```

**Current Reality**: 
- `keywords_loader.py` looks for `config/threat_keywords.json` FIRST
- This is a **symlink** to `config_data/threat_keywords.json`
- **Result**: Always loads from `config_data/threat_keywords.json` (via symlink)

**Modules that import from `keywords_loader.py`**:
- ✅ `threat_scorer.py` - Imports `SEVERE_TERMS`, `MOBILITY_TERMS`, `INFRA_TERMS`
- ✅ `risk_shared.py` - Imports `CATEGORY_KEYWORDS`, `DOMAIN_KEYWORDS`, etc.
- ✅ `rss_processor.py` - Imports `KEYWORD_DATA` for RSS filtering
- ✅ `health_check.py` - Imports `get_all_keywords()`

### 2. **Location Keywords** (`rss_processor.py` + `feeds_catalog.py`)

**Loading in `rss_processor.py`**:
```python
# Line ~1097-1100 in rss_processor.py
path = os.path.join(os.path.dirname(__file__), "config", "location_keywords.json")
with open(path, "r", encoding="utf-8") as f:
    location_data = json.load(f)
```

**Result**: Loads from `config/location_keywords.json` which is a **symlink** to `config_data/location_keywords.json`

---

## ✅ What's Actually Being Used

### **Threat Keywords**:
| File | Type | Used By | Purpose |
|------|------|---------|---------|
| `config_data/threat_keywords.json` | ✅ Real file | All modules via symlink | **SOURCE OF TRUTH** |
| `config/threat_keywords.json` | 🔗 Symlink | `keywords_loader.py` | Points to config_data/ |

### **Location Keywords**:
| File | Type | Used By | Purpose |
|------|------|---------|---------|
| `config_data/location_keywords.json` | ✅ Real file | All modules via symlink | **SOURCE OF TRUTH** |
| `config/location_keywords.json` | 🔗 Symlink | `rss_processor.py`, `feeds_catalog.py` | Points to config_data/ |

**Architecture**: ✅ **Optimal** - Single source of truth with backward-compatible symlinks

---

## 🧹 Current Architecture: Already Optimized!

### ✅ **No Cleanup Needed**

Your keyword architecture is **already optimized** with:
- ✅ Single source of truth in `config_data/`
- ✅ Backward-compatible symlinks in `config/`
- ✅ No duplicate data
- ✅ Clean, maintainable structure

### 📐 **Architecture Diagram**

```
config_data/ (Real files - Edit these)
├── threat_keywords.json     ← 39,638 bytes - SOURCE OF TRUTH
├── location_keywords.json   ← 51,468 bytes - SOURCE OF TRUTH
├── plans.py
└── risk_profiles.json

config/ (Symlinks for backward compatibility)
├── threat_keywords.json     → ../config_data/threat_keywords.json
└── location_keywords.json   → ../config_data/location_keywords.json

Loading Path:
keywords_loader.py → config/threat_keywords.json (symlink) → config_data/threat_keywords.json (real)
rss_processor.py   → config/location_keywords.json (symlink) → config_data/location_keywords.json (real)
```

### 🎯 **Why This Architecture**

1. **Single Source of Truth**: All keyword data lives in `config_data/`
2. **Backward Compatibility**: Code expecting `config/` still works via symlinks
3. **Centralized Data**: All configuration data organized in `config_data/` package
4. **No Duplication**: Symlinks ensure data consistency without copying files

### ⚠️ **Important: Always Edit config_data/**

When editing keywords, **always edit the files in `config_data/`**, not the symlinks:

```bash
# ✅ CORRECT
vim config_data/threat_keywords.json

# ❌ WRONG (edits will work but less clear)
vim config/threat_keywords.json  # This resolves to config_data/ anyway
```

---

## 📝 Keyword Management Workflow

### **To Add/Edit Threat Keywords**:

1. **Edit the SOURCE file** (not the symlink):
   ```bash
   vim config_data/threat_keywords.json
   ```

2. **Validate changes**:
   ```bash
   python validate_keywords.py --path config_data/threat_keywords.json
   ```

3. **Test loading**:
   ```bash
   python -c "from keywords_loader import KEYWORD_DATA; print(f'Loaded {len(KEYWORD_DATA[\"keywords\"])} keywords')"
   ```

4. **Commit**:
   ```bash
   git add config_data/threat_keywords.json
   git commit -m "feat: add new threat keywords - [description]"
   ```

### **To Add/Edit Location Keywords**:

1. **Edit the SOURCE file** (not the symlink):
   ```bash
   vim config_data/location_keywords.json
   ```

2. **Test loading**:
   ```bash
   python -c "import json; data = json.load(open('config_data/location_keywords.json')); print(f'Cities: {len(data[\"cities\"])}, Countries: {len(data[\"countries\"])}')"
   ```

3. **Commit**:
   ```bash
   git add config_data/location_keywords.json
   git commit -m "feat: add new locations - [description]"
   ```

---

## 🎯 Summary

### **ARCHITECTURE STATUS**: ✅ **OPTIMAL**

- ✅ **Clear**: Single source of truth in `config_data/` directory
- ✅ **Compatible**: Symlinks in `config/` for backward compatibility
- ✅ **Efficient**: No duplicate data, 91 KB total (not 182 KB)
- ✅ **Maintainable**: Clear separation between real files and symlinks

### **Single Source of Truth**:
```
config_data/
├── threat_keywords.json     ← Edit this for threat keywords (261 base + 23 categories)
└── location_keywords.json   ← Edit this for location keywords (339 cities + 224 countries)
```

### **Symlinks** (for backward compatibility):
```
config/
├── threat_keywords.json     → ../config_data/threat_keywords.json
└── location_keywords.json   → ../config_data/location_keywords.json
```

### **Loaded By**:
- `threat_keywords.json` → `keywords_loader.py` → Used by threat_scorer, risk_shared, rss_processor
- `location_keywords.json` → `rss_processor.py`, `feeds_catalog.py`

### **Data Flow**:
```
1. You edit: config_data/threat_keywords.json
2. Code imports: from keywords_loader import KEYWORD_DATA
3. Loader reads: config/threat_keywords.json (symlink)
4. Symlink resolves to: config_data/threat_keywords.json
5. Result: Your changes are loaded ✅
```

---

## 📚 Related Documentation

- `KEYWORDS_README.md` - Usage guide for keyword loader
- `KEYWORDS_VALIDATION.md` - Validation procedures
- `KEYWORDS_VALIDATION_COMPLETE.md` - Implementation status
- `validate_keywords.py` - Validation script
- `keywords_loader.py` - Central keyword loader module

---

## ✅ Action Items

1. **Immediate**: Delete `config_data/threat_keywords.json` (duplicate)
2. **Immediate**: Delete `config_data/location_keywords.json` (duplicate)
3. **Update**: Fix any references to `config_data/` in documentation
4. **Document**: This file serves as the authoritative reference

**Status**: Ready for cleanup - No code changes needed, just file deletion.
