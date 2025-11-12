"""
Rate Limiting Configuration Guide

Add these environment variables for production deployment:

# OpenAI Rate Limits (adjust based on your tier)
OPENAI_TPM_LIMIT=3000      # Tokens per minute (Tier 1: ~3000, Tier 2: ~30000)

# XAI/Grok Rate Limits 
XAI_TPM_LIMIT=1500         # Conservative estimate for Grok API

# DeepSeek Rate Limits (typically generous)
DEEPSEEK_TPM_LIMIT=5000    # DeepSeek is usually more permissive

# Moonshot Rate Limits (Chinese provider, moderate limits)  
MOONSHOT_TPM_LIMIT=1000    # Conservative for international usage

# Circuit Breaker Configuration (optional - uses defaults if not set)
CB_FAILURE_THRESHOLD=5     # Failures before circuit opens
CB_RECOVERY_TIMEOUT=300    # Seconds before attempting recovery (5 min)

Usage Examples:
==============

For Railway deployment, add to environment variables:
OPENAI_TPM_LIMIT=3000
XAI_TPM_LIMIT=1500
DEEPSEEK_TPM_LIMIT=5000
MOONSHOT_TPM_LIMIT=1000

For local development with higher limits:
OPENAI_TPM_LIMIT=10000
XAI_TPM_LIMIT=5000
DEEPSEEK_TPM_LIMIT=10000
MOONSHOT_TPM_LIMIT=3000

Monitoring:
==========

Check rate limiting status via API:
- GET /api/metrics/rate-limits (if implemented)
- Monitor logs for rate limiting events
- Watch for circuit breaker state changes

Production Notes:
================

1. Start with conservative limits
2. Monitor actual usage patterns
3. Adjust limits based on provider tiers
4. Set up alerting for circuit breaker opens
5. Consider time-of-day variations in limits
"""

# For immediate testing, add to your .env file:
ENV_VARS = {
    "OPENAI_TPM_LIMIT": "3000",
    "XAI_TPM_LIMIT": "1500", 
    "DEEPSEEK_TPM_LIMIT": "5000",
    "MOONSHOT_TPM_LIMIT": "1000"
}

if __name__ == "__main__":
    print("Rate Limiting Configuration:")
    for key, value in ENV_VARS.items():
        print(f"export {key}={value}")
    print("\nAdd these to your .env file or Railway environment variables")
