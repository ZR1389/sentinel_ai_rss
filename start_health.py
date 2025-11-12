#!/usr/bin/env python3
"""
start_health.py - Railway startup wrapper for health_check.py

Ensures proper Railway environment setup and graceful error handling.
"""

import os
import sys
import logging

# Configure logging for Railway
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    """Start health check server with Railway compatibility."""
    
    # Get port from Railway
    port = os.getenv('PORT', '8080')
    try:
        port = int(port)
    except (ValueError, TypeError):
        logger.error(f"Invalid PORT value: {port}")
        port = 8080
    
    logger.info(f"Starting Sentinel AI health server on port {port}")
    logger.info(f"Environment: {os.getenv('RAILWAY_ENVIRONMENT', 'development')}")
    
    # Set required environment variables if missing
    if not os.getenv('PYTHONPATH'):
        os.environ['PYTHONPATH'] = os.getcwd()
    
    try:
        # Try to start uvicorn with health_check
        import uvicorn
        from health_check import app
        
        logger.info("Starting FastAPI health server with uvicorn")
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=port,
            log_level="info",
            access_log=False  # Reduce log noise in Railway
        )
        
    except ImportError as e:
        logger.error(f"Failed to import required modules: {e}")
        logger.info("Falling back to railway_health.py")
        
        # Fallback to railway_health
        try:
            from railway_health import app
            import uvicorn
            uvicorn.run(app, host="0.0.0.0", port=port)
        except Exception as e2:
            logger.error(f"Fallback also failed: {e2}")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Failed to start health server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
