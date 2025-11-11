# Sentinel AI RSS - Directory Structure

This document describes the organized directory structure for the Sentinel AI RSS project.

## 📁 Root Directory Structure

```
sentinel_ai_rss/
├── 📄 Core Application Files
│   ├── main.py                 # FastAPI main application
│   ├── advisor.py              # Main advisory generation logic
│   ├── chat_handler.py         # Chat interface handling
│   ├── threat_engine.py        # Threat analysis engine
│   ├── rss_processor.py        # RSS feed processing
│   └── llm_router.py           # LLM provider routing logic
│
├── 🔧 LLM Client Modules
│   ├── deepseek_client.py      # DeepSeek AI integration
│   ├── openai_client_wrapper.py # OpenAI API wrapper
│   ├── xai_client.py           # Grok/xAI integration
│   └── moonshot_client.py      # Moonshot AI integration
│
├── 🛠️ Utility Modules
│   ├── db_utils.py             # Database utilities
│   ├── auth_utils.py           # Authentication utilities
│   ├── city_utils.py           # Geographic processing
│   ├── email_dispatcher.py     # Email notifications
│   ├── push_dispatcher.py      # Push notifications
│   ├── telegram_dispatcher.py  # Telegram integration
│   └── translation_utils.py    # Multi-language support
│
├── 📂 config/                  # Configuration Files
│   ├── location_keywords.json  # Geographic keywords
│   ├── risk_profiles.json      # Risk assessment profiles
│   ├── threat_keywords.json    # Threat detection keywords
│   ├── monitoring_results_*.json # Performance monitoring data
│   ├── .env.bak                # Environment backup
│   └── .env.speed.example      # Environment template
│
├── 📂 data/                    # Data & Schema Files
│   └── sentinel_schema_final.sql # Database schema
│
├── 📂 tests/                   # Test Suite
│   ├── advisor/                # Advisor-specific tests
│   │   ├── test_advisor_improvements.py
│   │   ├── test_advisor_priority.py
│   │   ├── test_advisor_verbosity.py
│   │   ├── test_confidence_scoring.py
│   │   └── test_role_duplication_fix.py
│   │
│   ├── llm/                    # LLM routing tests
│   │   └── test_llm_provider_priority.py
│   │
│   ├── geographic/             # Geographic processing tests
│   │   ├── test_geographic_improvements.py
│   │   └── test_geographic_validation.py
│   │
│   ├── performance/            # Performance & load tests
│   │   ├── load_test.py
│   │   ├── monitor_performance.py
│   │   └── test_optimizations.py
│   │
│   ├── integration/            # Integration tests
│   ├── deprecated/             # Deprecated tests
│   └── analysis/               # Test analysis scripts
│
├── 📂 docs/                    # Documentation
│   ├── CLEANUP_SUMMARY.md      # Code cleanup documentation
│   └── OPTIMIZATION_SUMMARY.md # Performance optimization notes
│
├── 📂 scripts/                 # Utility Scripts
│   └── geocode_alerts.py       # Geocoding utilities
│
├── 📂 web/                     # Web Assets
│   └── countries.geojson       # Geographic boundaries
│
├── 📂 fonts/                   # Font Files
│   └── NotoSans-Regular.ttf    # PDF generation fonts
│
├── 📂 cache/                   # Runtime Cache
│   └── alerts-*.json          # Cached alert data
│
├── 📂 logs/                    # Application Logs
│   └── sentinel-log-*.txt     # Daily log files
│
├── 📂 reports/                 # Generated Reports
│   └── *.pdf                  # User reports
│
├── 📂 archive/                 # Archived Files
│
└── 📄 Configuration Files
    ├── .env                    # Environment variables
    ├── requirements.txt        # Python dependencies
    ├── pyproject.toml         # Project configuration
    ├── Dockerfile             # Container configuration
    └── Procfile               # Deployment configuration
```

## 🎯 Key Organization Principles

### 1. **Separation of Concerns**
- Core application logic in root
- Tests organized by functionality
- Configuration isolated in `config/`
- Documentation in `docs/`

### 2. **LLM Provider Priority** (Updated Nov 2025)
```
Grok (Primary) → OpenAI (Secondary) → Moonshot (Tertiary) → DeepSeek (Fallback)
```

### 3. **Test Organization**
- `tests/advisor/` - Advisory generation testing
- `tests/llm/` - LLM routing and provider testing
- `tests/geographic/` - Location processing testing
- `tests/performance/` - Load and optimization testing

### 4. **Clean Root Directory**
- Only essential application files in root
- No scattered test files
- Clear separation of runtime vs configuration data

## 🔧 Recent Changes (Nov 2025)

### Moved Files:
- All `test_*.py` files → `tests/` subdirectories
- `*.json` configuration → `config/`
- `*.sql` schema files → `data/`
- `*.md` documentation → `docs/`
- Performance monitoring → `tests/performance/`

### Updated Configuration:
- LLM provider priority reordered to prioritize paid providers
- Timeout optimization for better reliability
- Environment variables reorganized for clarity

## 📋 Usage Guidelines

### Running Tests:
```bash
# Advisor tests
python -m pytest tests/advisor/

# LLM routing tests  
python -m pytest tests/llm/

# All tests
python -m pytest tests/
```

### Configuration:
- Main environment: `.env`
- Backups and examples: `config/`
- Schema updates: `data/`

### Development:
- Add new tests to appropriate `tests/` subdirectory
- Keep root directory clean
- Use configuration files from `config/` directory
