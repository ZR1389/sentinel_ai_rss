#!/usr/bin/env python3
"""
PostGIS Installation Script for Railway Deployment
Run this as a one-off Railway job or include in startup
"""
import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def install_postgis():
    """Install PostGIS extension via direct psycopg2 connection"""
    try:
        import psycopg2
        from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
        
        db_url = os.getenv('DATABASE_URL')
        if not db_url:
            logger.error("DATABASE_URL not set")
            return False
        
        logger.info("Connecting to database...")
        conn = psycopg2.connect(db_url)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        
        # Check if PostGIS already exists
        cur.execute("""
            SELECT extname, extversion 
            FROM pg_extension 
            WHERE extname = 'postgis';
        """)
        result = cur.fetchone()
        
        if result:
            logger.info(f"✓ PostGIS already installed: {result[0]} v{result[1]}")
            
            # Check version details
            cur.execute("SELECT PostGIS_Version();")
            version = cur.fetchone()
            if version:
                logger.info(f"  Full version: {version[0]}")
        else:
            logger.info("Installing PostGIS extension...")
            cur.execute("CREATE EXTENSION postgis;")
            logger.info("✓ PostGIS extension installed successfully")
            
            # Verify
            cur.execute("SELECT PostGIS_Version();")
            version = cur.fetchone()
            if version:
                logger.info(f"✓ PostGIS version: {version[0]}")
        
        # Check available spatial functions
        cur.execute("""
            SELECT COUNT(*) 
            FROM pg_proc 
            WHERE proname LIKE 'st_%';
        """)
        func_count = cur.fetchone()[0]
        logger.info(f"✓ {func_count} spatial functions available")
        
        cur.close()
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"✗ PostGIS installation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("PostGIS Installation Check")
    logger.info("=" * 50)
    
    success = install_postgis()
    
    if success:
        logger.info("=" * 50)
        logger.info("✓ PostGIS ready for geocoding service")
        logger.info("=" * 50)
        sys.exit(0)
    else:
        logger.error("=" * 50)
        logger.error("✗ PostGIS installation failed")
        logger.error("=" * 50)
        sys.exit(1)
