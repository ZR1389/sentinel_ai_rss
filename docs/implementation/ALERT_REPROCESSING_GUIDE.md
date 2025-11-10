# Alert Reprocessing Guide

This document provides guidance on the best approaches for reprocessing existing alerts in your Sentinel AI database to apply new improvements like HTML cleaning, threat analysis updates, and other enhancements.

## Overview

With the recent implementation of HTML cleaning in the RSS processor and other improvements to the threat analysis pipeline, you may want to reprocess existing alerts in your database to apply these enhancements retroactively.

## Available Approaches

### 1. HTML Cleaning Only (Recommended for HTML Issues)

**Script:** `scripts/reprocess_alert_html.py`

This is the fastest and most focused approach for fixing HTML display issues in your frontend map. It only updates the `title` and `summary` fields to remove HTML tags and formatting problems.

**When to use:**
- You're seeing HTML tags or entities in your frontend map
- You want to quickly clean up alert content for better readability
- You don't need to update threat scores or other analysis

**Usage:**
```bash
# Test what would be cleaned (recommended first step)
python scripts/reprocess_alert_html.py --dry-run --days-back=30

# Clean recent alerts (last 30 days)
python scripts/reprocess_alert_html.py --days-back=30

# Clean all alerts in batches of 50
python scripts/reprocess_alert_html.py --days-back=0 --batch-size=50

# Clean up to 1000 alerts from last 7 days
python scripts/reprocess_alert_html.py --days-back=7 --max-alerts=1000
```

**Performance:** Very fast - processes 100-200 alerts per minute
**Risk:** Low - only modifies display fields, no analysis changes

### 2. Full Threat Engine Reprocessing (For Comprehensive Updates)

**Script:** `scripts/reprocess_via_threat_engine.py`

This approach runs alerts through the complete threat engine pipeline, updating threat scores, risk analysis, LLM summaries, and HTML cleaning all in one pass.

**When to use:**
- You've made significant improvements to threat analysis logic
- You want to update threat scores with new algorithms
- You need to regenerate LLM summaries with current models
- You want comprehensive reprocessing including HTML cleaning

**Usage:**
```bash
# Test comprehensive reprocessing (recommended first step)
python scripts/reprocess_via_threat_engine.py --dry-run --days-back=7

# Reprocess recent alerts with full analysis
python scripts/reprocess_via_threat_engine.py --days-back=7

# Reprocess smaller batches (recommended for large datasets)
python scripts/reprocess_via_threat_engine.py --days-back=14 --batch-size=25 --max-alerts=500
```

**Performance:** Slower - processes 10-30 alerts per minute (depends on LLM calls)
**Risk:** Medium - updates many fields, uses API calls
**Cost:** Higher - makes LLM API calls for enhanced analysis

## Recommended Workflow

### For HTML Issues (Current Need)

Based on your recent HTML cleaning implementation, here's the recommended approach:

1. **Test first:**
   ```bash
   python scripts/reprocess_alert_html.py --dry-run --days-back=30 --batch-size=10
   ```

2. **Process recent alerts:**
   ```bash
   python scripts/reprocess_alert_html.py --days-back=30
   ```

3. **Process older alerts in batches:**
   ```bash
   # Process all alerts in manageable batches
   python scripts/reprocess_alert_html.py --days-back=0 --batch-size=100
   ```

### For Future Comprehensive Updates

When you make significant improvements to threat analysis:

1. **Test with small batch:**
   ```bash
   python scripts/reprocess_via_threat_engine.py --dry-run --days-back=3 --batch-size=10
   ```

2. **Process gradually:**
   ```bash
   # Process last week's alerts
   python scripts/reprocess_via_threat_engine.py --days-back=7 --batch-size=25
   ```

## Script Parameters

### Common Parameters

- `--dry-run`: Show what would be changed without making updates
- `--days-back=N`: Only process alerts from last N days (0 = all alerts)
- `--batch-size=N`: Number of alerts to process per batch (default varies)
- `--max-alerts=N`: Maximum total alerts to process (0 = unlimited)

### HTML Cleaning Script Specific

- Default batch size: 100 (optimized for speed)
- Checks if content actually needs cleaning before updating
- Logs before/after samples for verification
- Very safe - only updates display fields

### Threat Engine Script Specific

- Default batch size: 50 (smaller due to LLM processing)
- Runs full threat analysis pipeline
- Updates threat scores, risks, LLM summaries
- More resource intensive

## Monitoring and Logs

Both scripts create detailed logs in `logs/`:
- `logs/reprocess_html_cleaning.log` - HTML cleaning operations
- `logs/reprocess_threat_engine.log` - Full reprocessing operations

Log files include:
- Processing statistics
- Before/after content samples
- Error details if any issues occur
- Performance metrics

## Performance Expectations

### HTML Cleaning Script
- **Speed:** ~100-200 alerts/minute
- **Update Rate:** ~40-60% of alerts need cleaning (based on test)
- **Resource Usage:** Low CPU, minimal database load
- **Recommended Batch Size:** 100-200

### Threat Engine Script  
- **Speed:** ~10-30 alerts/minute (varies with LLM response time)
- **Update Rate:** 100% (all alerts get full reprocessing)
- **Resource Usage:** Moderate CPU, significant LLM API usage
- **Recommended Batch Size:** 25-50

## Current Status

Based on the test run, your database has:
- **350 alerts** in the last 7 days
- **159 alerts (45.4%)** that need HTML cleaning
- Common issues: `<img>` tags, HTML entities, `<p>` tags, RSS footers

## Cost Considerations

### HTML Cleaning
- **Database Impact:** Minimal - simple UPDATE queries
- **API Costs:** None
- **Time Investment:** Low - can process thousands quickly

### Threat Engine Reprocessing
- **Database Impact:** Moderate - updates many fields per alert
- **API Costs:** Significant - makes LLM API calls per alert
- **Time Investment:** High - slower processing due to AI analysis

## Safety Features

Both scripts include:
- **Dry run mode** - test before making changes
- **Batch processing** - prevents database overload
- **Error handling** - continues on individual failures
- **Progress logging** - track processing status
- **Interrupt handling** - can safely stop with Ctrl+C

## Next Steps

For your current HTML display issue:

1. **Run the HTML cleaning script** on recent alerts to fix the immediate map display problem
2. **Monitor the results** to ensure the cleaning works as expected
3. **Consider running periodically** on older alerts if needed

For future improvements:
1. **Use threat engine reprocessing** when you make significant analytical improvements
2. **Test with small batches first** to validate results
3. **Consider the cost/benefit** of full reprocessing vs. new alert processing

## Support

If you encounter issues:
1. Check the log files in `logs/` for detailed error information
2. Use `--dry-run` mode to test before applying changes
3. Start with small batches to identify any problems
4. The scripts are designed to be safe and resumable
