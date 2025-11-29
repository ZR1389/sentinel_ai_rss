# Environment Management Guide

## Overview

You now have **3 environment files**:

1. **`.env.development`** - Safe for local testing (minimal costs)
2. **`.env.production`** - Full production config (for Railway)
3. **`.env`** - Currently active (symlink or copy one of the above)

## How to Switch Environments

### For Local Development (Safe, No Quota Burns)

```bash
cp .env.development .env
```

**What's different:**
- Uses SQLite database (not Railway PostgreSQL)
- Only DeepSeek LLM (cheapest option)
- Apify/ACLED/SOCMINT disabled
- Push notifications disabled
- Low quotas (100 embeddings/day)
- Localhost CORS

### For Production Testing (BE CAREFUL)

```bash
cp .env.production .env
```

**What's enabled:**
- Railway PostgreSQL database
- All LLM providers (Grok, OpenAI, Moonshot, DeepSeek)
- ACLED, Apify, SOCMINT (costs money)
- Push notifications
- Production quotas

## Cost Comparison

| Service | Development | Production |
|---------|-------------|------------|
| Database | SQLite (free) | Railway Postgres |
| LLMs | DeepSeek only (~$0.001/call) | All providers |
| SOCMINT | Disabled | Apify ($$$) |
| ACLED | Disabled | 100 calls/day limit |
| Geocoding | Disabled | Enabled (API calls) |
| Redis | In-memory | Optional cloud Redis |

## Current Status

**Your current `.env` file has PRODUCTION credentials!**

Run this now to switch to safe development mode:

```bash
cp .env.development .env
```

## Railway Deployment

Railway reads environment variables from its **Dashboard > Variables**, NOT from `.env` files.

To update production:
1. Go to Railway dashboard
2. Navigate to your service > Variables
3. Paste values from `.env.production`
4. Railway will auto-redeploy

## Best Practice Workflow

```bash
# 1. Always start in development mode
cp .env.development .env

# 2. Test your code locally
python main.py

# 3. When ready to deploy, commit and push
git add .
git commit -m "Add feature X"
git push

# 4. Railway auto-deploys using its dashboard variables
```

## Safety Checklist

Before running locally, verify:
- [ ] `ENV=development` in your `.env`
- [ ] `DATABASE_URL=sqlite:///` (not Railway)
- [ ] `APIFY_API_TOKEN=` is empty
- [ ] `ACLED_ENABLED=false`
- [ ] Only one cheap LLM provider enabled

## Emergency: Burned Quotas?

If you accidentally ran production config locally:

1. Check usage:
   - OpenAI: https://platform.openai.com/usage
   - xAI/Grok: https://console.x.ai/
   - Apify: https://console.apify.com/billing

2. Disable expensive providers in Railway if needed

3. Set rate limits in code (already done for travel risk endpoint)
