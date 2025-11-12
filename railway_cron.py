#!/usr/bin/env python3
"""
Railway Cron Job Script for Data Retention
Handles environment loading and error recovery for Railway cron execution
"""

import os
import sys
import logging

def setup_cron_environment():
    """Setup environment for Railway cron job execution"""
    
    # Set working directory to app directory
    if os.path.exists('/app'):
        os.chdir('/app')
    
    # Add app directory to Python path
    if '/app' not in sys.path:
        sys.path.insert(0, '/app')
    
    # Setup basic logging for cron job
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger('railway_cron')
    
    # Check critical environment variables
    required_vars = ['DATABASE_URL']
    missing_vars = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {missing_vars}")
        logger.info("Available environment variables:")
        for key, value in os.environ.items():
            if any(keyword in key.upper() for keyword in ['DATABASE', 'DB', 'URL', 'RAILWAY']):
                logger.info(f"  {key}={'*' * len(value) if 'KEY' in key or 'SECRET' in key or 'PASSWORD' in key else value}")
        
        # Try to load from potential config sources
        logger.info("Trying alternative configuration sources...")
        return False
    
    # Set a flag to indicate cron environment for fallback logic
    os.environ['RAILWAY_CRON_MODE'] = 'true'
    
    logger.info("Environment setup completed successfully")
    return True

def run_retention_cleanup():
    """Run the retention cleanup with proper error handling"""
    
    logger = logging.getLogger('railway_cron')
    
    try:
        # Import and run retention worker
        from retention_worker import cleanup_old_alerts
        
        logger.info("Starting retention cleanup...")
        cleanup_old_alerts()
        logger.info("Retention cleanup completed successfully")
        return True
        
    except ImportError as e:
        logger.error(f"Import error: {e}")
        logger.error("Make sure retention_worker.py is available in the current directory")
        return False
    except Exception as e:
        logger.error(f"Retention cleanup failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

def run_vacuum():
    """Run database vacuum with proper error handling"""
    
    logger = logging.getLogger('railway_cron')
    
    try:
        # Import and run vacuum
        from retention_worker import perform_vacuum
        
        logger.info("Starting database vacuum...")
        perform_vacuum()
        logger.info("Database vacuum completed successfully")
        return True
        
    except ImportError as e:
        logger.error(f"Import error: {e}")
        return False
    except Exception as e:
        logger.error(f"Database vacuum failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

if __name__ == "__main__":
    # Setup environment
    if not setup_cron_environment():
        sys.exit(1)
    
    # Determine what operation to run based on command line argument
    if len(sys.argv) > 1:
        operation = sys.argv[1]
        
        if operation == "cleanup":
            success = run_retention_cleanup()
        elif operation == "vacuum":
            success = run_vacuum()
        else:
            print(f"Unknown operation: {operation}")
            print("Usage: python railway_cron.py [cleanup|vacuum]")
            sys.exit(1)
    else:
        # Default to cleanup
        success = run_retention_cleanup()
    
    sys.exit(0 if success else 1)
