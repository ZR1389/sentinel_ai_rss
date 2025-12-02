# run_migrations.py — Postgres migration runner for Sentinel AI
import os
from pathlib import Path
from utils.db_utils import execute, fetch_one
import logging

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

def get_db_version() -> int:
    """Get current schema version from database."""
    try:
        execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
        result = fetch_one("SELECT MAX(version) FROM schema_version")
        return result[0] if result and result[0] is not None else 0
    except Exception as e:
        logger.error(f"Failed to get DB version: {e}")
        return 0

def set_db_version(version: int):
    """Set schema version in database."""
    try:
        execute("INSERT INTO schema_version (version) VALUES (%s) ON CONFLICT (version) DO NOTHING", (version,))
        logger.info(f"Set schema version to {version}")
    except Exception as e:
        logger.error(f"Failed to set DB version: {e}")
        raise

def run_migrations():
    """Apply all pending migrations in order."""
    current_version = get_db_version()
    logger.info(f"Current schema version: {current_version}")
    
    if not MIGRATIONS_DIR.exists():
        logger.warning(f"Migrations directory not found: {MIGRATIONS_DIR}")
        return
    
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    
    if not migration_files:
        logger.info("No migration files found.")
        return
    
    applied_count = 0
    for migration_file in migration_files:
        # Extract version from filename (e.g., "001_create_table.sql" -> 1)
        try:
            version = int(migration_file.stem.split('_')[0])
        except (ValueError, IndexError):
            logger.warning(f"Skipping invalid migration filename: {migration_file.name}")
            continue
        
        if version > current_version:
            logger.info(f"Applying migration {migration_file.name} (version {version})...")
            try:
                sql = migration_file.read_text()
                # Split by semicolon and execute each statement separately
                statements = [stmt.strip() for stmt in sql.split(';') if stmt.strip()]
                for stmt in statements:
                    execute(stmt)
                set_db_version(version)
                applied_count += 1
                print(f"✓ Applied migration {migration_file.name} (version {version})")
            except Exception as e:
                logger.error(f"Failed to apply migration {migration_file.name}: {e}")
                print(f"✗ Failed migration {migration_file.name}: {e}")
                raise
    
    if applied_count == 0:
        print("No new migrations to apply.")
    else:
        print(f"Migrations complete. Applied {applied_count} migration(s).")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        run_migrations()
    except Exception as e:
        logger.error(f"Migration runner failed: {e}", exc_info=True)
        exit(1)
