# URGENT: Configure Cron Jobs in Railway Dashboard

## Problem
Maps are not loading alerts because:
1. ✅ RSS processor IS working (3,754 raw alerts ingested in last 7 days)
2. ❌ Threat engine is NOT running (only 60 enriched alerts, none since Dec 1)

## Root Cause
Cron jobs are commented out in `railway.toml` because **railway.toml cron configuration doesn't work on Railway**.

The jobs MUST be configured manually in Railway Dashboard under:
**Settings → Cron Jobs**

## Required Cron Jobs

### 1. RSS Ingestion
- **Command**: `python railway_cron.py rss`
- **Schedule**: `0 6,18 * * *` (6am and 6pm UTC daily)
- **Purpose**: Ingest new articles from RSS feeds into raw_alerts table

### 2. Threat Engine Enrichment ⚠️ CRITICAL - MISSING!
- **Command**: `python railway_cron.py engine`
- **Schedule**: `0 7,19 * * *` (7am and 7pm UTC daily - 1 hour after RSS)
- **Purpose**: Process raw_alerts → enrich → store in alerts table (THIS IS MISSING!)

### 3. Geocoding Backfill
- **Command**: `python railway_cron.py geocode`
- **Schedule**: `30 3 * * *` (3:30am UTC daily)
- **Purpose**: Fill in missing coordinates for alerts

### 4. Proximity Check
- **Command**: `python railway_cron.py proximity`
- **Schedule**: `0 8,20 * * *` (8am and 8pm UTC daily)
- **Purpose**: Check traveler locations against threat areas

### 5. Retention Cleanup
- **Command**: `python railway_cron.py cleanup`
- **Schedule**: `0 */6 * * *` (every 6 hours)
- **Purpose**: Delete old alerts per retention policy

### 6. Database Vacuum
- **Command**: `python railway_cron.py vacuum`
- **Schedule**: `0 2 * * *` (2am UTC daily)
- **Purpose**: Optimize database performance

### 7. Daily Notifications
- **Command**: `python railway_cron.py notify`
- **Schedule**: `0 8 * * *` (8am UTC daily)
- **Purpose**: Send email reports to users

## How to Add in Railway Dashboard

1. Go to: https://railway.app → your project
2. Click on service "sentinel_ai_rss"
3. Go to **Settings** tab
4. Scroll to **Cron Jobs** section
5. Click **+ New**
6. Fill in:
   - Name: (e.g., "RSS Ingest")
   - Command: `python railway_cron.py rss`
   - Schedule: `0 6,18 * * *`
7. Click Save
8. Repeat for each job

## Why NOT in railway.toml?
Railway.com discontinued support for cron jobs in `railway.toml` - they must be configured in Dashboard UI.

## Current Status
- RSS: ✅ Working (but only because it was added to Dashboard manually)
- Engine: ❌ NOT running (no cron job configured!)
- Maps: ❌ Empty (no enriched alerts being created)

## Action Required
Add the 7 cron jobs above to Railway Dashboard. The **Threat Engine** job is CRITICAL for maps to work.
