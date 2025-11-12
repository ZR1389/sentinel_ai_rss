#!/usr/bin/env python3
"""
vacuum_only.py - Standalone script for database vacuum operations
Simple script for Railway cron jobs to avoid command parsing issues
"""

if __name__ == "__main__":
    from retention_worker import perform_vacuum
    perform_vacuum()
