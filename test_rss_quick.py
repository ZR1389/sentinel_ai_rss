#!/usr/bin/env python3
"""Quick RSS test to diagnose why writes aren't happening"""
import os
import sys
import asyncio

# Set debug flags
os.environ['RSS_DEBUG'] = 'true'
os.environ['RSS_WRITE_TO_DB'] = 'true'
os.environ['RSS_BATCH_LIMIT'] = '10'
os.environ['RSS_ALLOWED_LANGS'] = ''  # Allow all languages

print("=== RSS Quick Test ===\n")

# Import after setting env
from rss_processor import ingest_all_feeds_to_db, _coalesce_all_feed_specs

async def main():
    # Check feeds first
    specs = _coalesce_all_feed_specs()
    print(f"✓ Found {len(specs)} feed specs")
    if specs:
        print(f"  First feed: {specs[0]['url'][:60]}...")
    print()
    
    # Run ingest (write disabled for safety)
    print("Running RSS ingest (write_to_db=False for testing)...")
    result = await ingest_all_feeds_to_db(limit=10, write_to_db=False)
    
    print(f"\n=== RESULT ===")
    print(f"  feeds_processed: {result.get('feeds_processed')}")
    print(f"  alerts_processed: {result.get('alerts_processed')}")
    print(f"  written_to_db: {result.get('written_to_db')}")
    
    if 'error' in result:
        print(f"  ERROR: {result['error']}")
        return False
    
    if result.get('alerts_processed', 0) == 0:
        print(f"\n⚠️  NO ALERTS PROCESSED!")
        print(f"  Check logs above for [RSS_DEBUG] skip messages")
        return False
    
    print(f"\n✓ RSS processing works! {result['alerts_processed']} alerts built")
    return True

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
