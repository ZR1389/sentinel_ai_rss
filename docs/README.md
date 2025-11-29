# Sentinel AI RSS - Organized Structure

## 🚀 Quick Start

This project has been organized into a clean directory structure. Here's how to work with it:

### Running Tests
```bash
# Run all organized tests
python run_tests.py

# Run specific test categories
python -m pytest tests/advisor/     # Advisor tests
python -m pytest tests/llm/        # LLM routing tests  
python -m pytest tests/geographic/ # Geographic processing
python -m pytest tests/performance/ # Performance tests
```

### Key Files
- **Main Application**: `main.py`
- **Core Logic**: `advisor.py`, `threat_engine.py`, `llm_router.py`
- **Configuration**: `.env` (active), `config/` (backups, examples)
- **Tests**: All organized under `tests/` with subdirectories
- **Documentation**: `docs/DIRECTORY_STRUCTURE.md`

### LLM Provider Priority (Updated Nov 2025)
```
🥇 Grok (Primary)    - Fastest paid provider
🥈 OpenAI (Secondary) - Reliable paid provider  
🥉 Moonshot (Tertiary) - Slower paid provider
🆓 DeepSeek (Fallback) - Free provider (last resort)
```

### Directory Organization
- `tests/advisor/` - Advisory generation tests
- `tests/llm/` - LLM provider routing tests
- `tests/geographic/` - Location processing tests
- `tests/performance/` - Load and optimization tests
- `config/` - Configuration files and backups
- `data/` - Database schemas and data files
- `docs/` - Documentation and summaries

## 📁 What Was Organized

### Moved from Root:
- ✅ All `test_*.py` files → `tests/` subdirectories  
- ✅ `*.json` configs → `config/`
- ✅ `*.sql` schemas → `data/`
- ✅ `*.md` docs → `docs/`
- ✅ Performance files → `tests/performance/`

### Clean Root Directory:
- Only essential application files remain
- Clear separation of concerns
- Easy navigation and development

See `docs/DIRECTORY_STRUCTURE.md` for complete details.
