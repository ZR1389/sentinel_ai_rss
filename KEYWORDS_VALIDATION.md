# Threat Keywords Management & Validation

This document outlines the management and validation procedures for `config/threat_keywords.json`.

## 📁 File Structure

```json
{
  "keywords": [
    "terrorism", "bombing", "shooting", ...
  ],
  "translated": {
    "assassination": {
      "en": ["assassination", "murder", "killing"],
      "es": ["asesinato", "homicidio", "matanza"],
      "fr": ["assassinat", "meurtre", "tuerie"],
      ...
    }
  },
  "conditional": {
    "broad_terms": [...],
    "impact_terms": [...]
  }
}
```

## ✅ Validation Rules

### Required Fields
- `keywords`: Array of base threat keywords (strings)
- All fields must be properly formatted JSON

### Content Standards
- Keywords must be non-empty strings
- No duplicate keywords (case-insensitive)
- Keywords should be under 200 characters
- Translated terms must be arrays of strings
- Empty or whitespace-only terms are not allowed

### Language Codes
- Use ISO 639-1 language codes: `en`, `es`, `fr`, `zh`, `ru`, `hi`, `sr`, `it`, `pt`, `de`
- Maintain consistency across translation categories

## 🛠 Validation Tools

### 1. Automated Validation
```bash
# Run validation script
python validate_keywords.py

# Strict validation (fails on warnings)
python validate_keywords.py --strict

# Custom path
python validate_keywords.py --path /path/to/keywords.json
```

### 2. Pre-Commit Validation
```bash
# Install pre-commit hook (run once)
chmod +x scripts/validate-keywords-hook.sh
ln -sf ../../scripts/validate-keywords-hook.sh .git/hooks/pre-commit

# Manual pre-commit check
./scripts/validate-keywords-hook.sh
```

### 3. Integration Testing
```bash
# Test keywords loading in application
python -c "from keywords_loader import KEYWORD_DATA; print('✅ Keywords loaded successfully')"
```

## 🔄 Review Schedule

### Monthly Review
- [ ] Check for new threat patterns in global news
- [ ] Review keyword effectiveness with threat detection metrics
- [ ] Update translations for new categories
- [ ] Remove outdated or ineffective keywords

### Quarterly Review  
- [ ] Analyze false positive/negative rates
- [ ] Review competitor keyword lists
- [ ] Update with security industry trends
- [ ] Validate translation accuracy with native speakers

### Annual Review
- [ ] Complete keyword taxonomy restructure if needed
- [ ] Update language priorities based on user base
- [ ] Archive historical keyword performance data
- [ ] Update validation rules and standards

## 📝 Change Process

### 1. Prepare Changes
```bash
# Create feature branch
git checkout -b update-keywords-YYYY-MM-DD

# Edit keywords file
vim config/threat_keywords.json

# Validate changes
python validate_keywords.py --strict
```

### 2. Test Integration
```bash
# Test keywords loading
python -c "from keywords_loader import validate_keywords; print('✅ Validation passed')"

# Test RSS processor integration
python -c "from rss_processor import load_keywords; print('✅ RSS integration works')"

# Run relevant tests
python -m pytest tests/ -k keyword
```

### 3. Document Changes
```bash
# Create change log entry
echo "$(date): Added keywords for [threat type] - [brief description]" >> docs/keywords_changelog.md

# Update version if major changes
# Increment version in keywords_loader.py header comment
```

### 4. Review & Merge
```bash
# Create PR with validation report
git add config/threat_keywords.json docs/keywords_changelog.md
git commit -m "Update threat keywords: [description]"
git push origin update-keywords-YYYY-MM-DD

# Include validation output in PR description
python validate_keywords.py > validation_report.txt
```

## 🚨 Emergency Updates

For urgent threat keyword updates (active threats, breaking news):

```bash
# Quick validation and deploy
python validate_keywords.py --strict
git add config/threat_keywords.json  
git commit -m "URGENT: Add keywords for [specific threat]"
git push origin main

# Immediate deployment notification
echo "Emergency keyword update deployed for: [threat description]" | \
  mail -s "Urgent Keywords Update" security-team@company.com
```

## 📊 Monitoring

### Validation Metrics
- Keywords loading success rate
- Translation completeness percentage
- Duplicate detection accuracy
- File size and performance impact

### Usage Metrics
- Keyword match frequency in RSS feeds
- False positive/negative rates
- Geographic effectiveness (by language)
- Category performance analysis

## 🔧 Troubleshooting

### Common Issues

**1. JSON Syntax Errors**
```bash
# Check JSON validity
python -m json.tool config/threat_keywords.json > /dev/null
```

**2. Keywords Loading Failures**
```bash
# Debug keywords loading
python -c "
from keywords_loader import _load_keyword_data
import logging
logging.basicConfig(level=logging.DEBUG)
data = _load_keyword_data()
print(f'Loaded {len(data.get(\"keywords\", []))} keywords')
"
```

**3. Translation Inconsistencies**
```bash
# Check translation coverage
python validate_keywords.py | grep "Translation Coverage" -A 20
```

### Recovery Procedures

**1. Corrupted Keywords File**
```bash
# Restore from git history
git checkout HEAD~1 -- config/threat_keywords.json
python validate_keywords.py
```

**2. Production Issues**
```bash
# Use fallback keywords
export THREAT_KEYWORDS_PATH=""  # Forces fallback mode
systemctl restart sentinel-rss
```

## 📈 Performance Considerations

- Keep base keywords list under 1000 entries for performance
- Use specific terms rather than broad categories
- Regular cleanup of unused historical keywords
- Monitor memory usage with large translation sets
- Consider keyword caching for high-frequency operations

---

## Version Control Integration

This file is tracked in version control to ensure:
- ✅ Change history and attribution
- ✅ Collaborative editing and review
- ✅ Rollback capability for problematic updates
- ✅ Branch-based feature development
- ✅ Automated validation on commits
