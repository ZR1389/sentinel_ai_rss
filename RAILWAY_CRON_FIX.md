# Railway Cron Job Fix

## Problem
Railway cron jobs were failing with `RuntimeError: DATABASE_URL not set` because environment variables weren't being passed to the cron execution context.

## Root Cause
- Railway cron jobs run in a minimal environment
- Environment variables from the main application aren't automatically available
- Direct Python imports failed because the working directory and Python path weren't set correctly

## Solution Implementation

### 1. Enhanced Retention Worker (`retention_worker.py`)
```python
# Added environment loading function
def load_environment():
    """Load environment variables for Railway deployment"""
    # Railway automatically provides DATABASE_URL in the environment
    # But for cron jobs, we need to ensure the environment is properly loaded
    
    if not os.getenv("DATABASE_URL"):
        # Try to load from various sources
        env_sources = [
            "/app/.env",  # Railway app directory
            ".env",       # Current directory
        ]
        
        for env_file in env_sources:
            if os.path.exists(env_file):
                # Load environment variables from file
```

### 2. Railway Cron Wrapper (`railway_cron.py`)
```python
def setup_cron_environment():
    """Setup environment for Railway cron job execution"""
    
    # Set working directory to app directory
    if os.path.exists('/app'):
        os.chdir('/app')
    
    # Add app directory to Python path
    if '/app' not in sys.path:
        sys.path.insert(0, '/app')
```

### 3. Updated Railway Configuration (`railway.toml`)
```toml
# Cron jobs for maintenance tasks
[[cron]]
  name = "retention-cleanup"
  command = "python railway_cron.py cleanup"
  schedule = "0 */6 * * *"  # Every 6 hours
  
[[cron]]
  name = "daily-vacuum"
  command = "python railway_cron.py vacuum"
  schedule = "0 2 * * *"    # Daily at 2 AM UTC
```

## Key Improvements

### 1. **Environment Loading**
- Automatic detection of DATABASE_URL from environment
- Fallback to reading from .env files if needed
- Clear error messages if environment variables are missing

### 2. **Path Management**
- Proper working directory setup (`/app` for Railway)
- Python path configuration for module imports
- Fallback imports for missing dependencies

### 3. **Error Handling**
- Comprehensive try-catch blocks for all operations
- Graceful degradation if vacuum operations fail (requires superuser)
- Detailed logging for debugging cron job issues

### 4. **Logging Fallbacks**
- Primary: Structured logging with logging_config
- Fallback: Basic Python logging if structured logging unavailable
- Mock metrics object to prevent import errors

## Testing

### Local Testing:
```bash
# Test the cron wrapper
python3 railway_cron.py cleanup
python3 railway_cron.py vacuum

# Test retention worker directly
python3 retention_worker.py
```

### Railway Production:
- Cron jobs will now run every 6 hours for cleanup
- Daily vacuum runs at 2 AM UTC
- All operations are logged for monitoring

## Benefits

1. **Reliability**: Robust environment handling prevents cron failures
2. **Monitoring**: Comprehensive logging for troubleshooting
3. **Graceful Degradation**: Operations continue even if some components fail
4. **Railway Optimized**: Specifically designed for Railway's cron environment

## Deployment

When you redeploy to Railway:
1. The new `railway_cron.py` wrapper will handle environment setup
2. Enhanced `retention_worker.py` has better error handling
3. Updated `railway.toml` uses the new cron commands
4. Cron jobs should now run successfully without DATABASE_URL errors

The retention cleanup will run every 6 hours, and database vacuum will run daily at 2 AM UTC, keeping your database optimized and preventing storage bloat.
