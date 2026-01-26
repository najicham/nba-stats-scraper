# Refactor Session R2: Scraper Infrastructure

**Scope:** 2 files, ~3,768 lines + 783-line function
**Risk Level:** Medium (foundational - all scrapers inherit from ScraperBase)
**Estimated Effort:** 2-3 hours
**Model:** Sonnet recommended

---

## Overview

Refactor the scraper base class into composable mixins and extract the monolithic Flask app factory into blueprints.

---

## Files to Refactor

### 1. scrapers/scraper_base.py (2,985 lines)

**Current State:** Single `ScraperBase` class with 45+ methods handling cost tracking, execution logging, validation, HTTP operations, event publishing, and configuration.

**Target Structure:**
```
scrapers/
├── scraper_base.py              # Core base class (~400 lines)
├── mixins/
│   ├── __init__.py
│   ├── cost_tracking_mixin.py   # Cost recording and finalization
│   ├── execution_logging_mixin.py # BigQuery execution logs
│   ├── validation_mixin.py      # Output validation, schema checks
│   ├── http_handler_mixin.py    # Download, retry strategies
│   ├── event_publisher_mixin.py # Pub/Sub event publishing
│   └── config_mixin.py          # Options, headers, URL management
```

**Methods to Extract:**

| Mixin | Methods |
|-------|---------|
| `CostTrackingMixin` | `_init_cost_tracking()`, `_record_cost_request()`, `_record_cost_retry()`, `_record_cost_export()`, `_finalize_cost_tracking()` |
| `ExecutionLoggingMixin` | `_get_scraper_name()`, `_determine_execution_source()`, `_determine_execution_status()`, `_extract_game_date()`, `_log_execution_to_bigquery()`, `_log_failed_execution_to_bigquery()`, `_log_scraper_failure_for_backfill()` |
| `ValidationMixin` | `_validate_scraper_output()`, `_validate_with_schema()`, `_validate_phase1_boundary()`, `_is_acceptable_zero_scraper_rows()`, + 5 more validation methods |
| `HttpHandlerMixin` | `download_and_decode()`, `set_http_downloader()`, `get_retry_strategy()`, `_handle_http_error()` |
| `EventPublisherMixin` | `_publish_completion_event_to_pubsub()`, `_publish_failed_event_to_pubsub()` |
| `ConfigMixin` | `set_opts()`, `validate_opts()`, `set_url()`, `set_headers()`, `set_additional_opts()`, + 3 more |

**Resulting ScraperBase:**
```python
class ScraperBase(
    CostTrackingMixin,
    ExecutionLoggingMixin,
    ValidationMixin,
    HttpHandlerMixin,
    EventPublisherMixin,
    ConfigMixin
):
    """Core scraper with run() orchestration."""

    def __init__(self, ...):
        # Initialize all mixins

    def run(self):
        # Core orchestration only (~100 lines)
```

### 2. scrapers/main_scraper_service.py - create_app() (783 lines)

**Current State:** Single `create_app()` function containing all route handlers, orchestration component loading, and endpoint logic.

**Target Structure:**
```
scrapers/
├── main_scraper_service.py      # App factory, config (~150 lines)
├── routes/
│   ├── __init__.py
│   ├── health.py                # Health check endpoint
│   ├── scraper.py               # /scrape endpoint
│   ├── orchestration.py         # /evaluate, /execute-workflows
│   ├── catchup.py               # /catchup endpoint
│   ├── cleanup.py               # /cleanup endpoint
│   └── schedule_fix.py          # /fix-stale-schedule endpoint
├── services/
│   └── orchestration_loader.py  # Lazy-load orchestration components
```

**Extraction Steps:**
1. Create `services/orchestration_loader.py` - Move lazy-load helper functions
2. Create route modules - Extract each endpoint handler
3. Update `create_app()` - Register blueprints, keep only app initialization

---

## Key Patterns to Follow

### Mixin Pattern for ScraperBase
```python
# mixins/cost_tracking_mixin.py
class CostTrackingMixin:
    """Mixin for tracking scraper costs."""

    def _init_cost_tracking(self):
        """Initialize cost tracking state."""
        self._cost_data = {
            'requests': 0,
            'retries': 0,
            'exports': 0
        }

    def _record_cost_request(self, url: str):
        """Record a cost request."""
        self._cost_data['requests'] += 1
        # ... implementation
```

### Blueprint Pattern for Routes
```python
# routes/scraper.py
from flask import Blueprint, request, jsonify

scraper_bp = Blueprint('scraper', __name__)

@scraper_bp.route('/scrape', methods=['POST'])
def scrape():
    """Execute a scraper based on request parameters."""
    # ... implementation
```

---

## Testing Strategy

**Critical:** ScraperBase is foundational. Test thoroughly.

```bash
# 1. Run existing scraper tests
python -m pytest tests/unit/scrapers/ -v

# 2. Verify a scraper still works after changes
python -c "from scrapers.nba.bdl_standings_scraper import BDLStandingsScraper; print('Import OK')"

# 3. Test the service endpoints
cd scrapers && python -c "from main_scraper_service import create_app; app = create_app(); print('App OK')"
```

---

## Success Criteria

- [ ] ScraperBase reduced to <400 lines (orchestration only)
- [ ] Each mixin file <300 lines
- [ ] create_app() reduced to <150 lines
- [ ] Each route module <200 lines
- [ ] All existing scrapers work without modification
- [ ] All scraper tests pass

---

## Files to Create

| File | Purpose | Estimated Lines |
|------|---------|-----------------|
| `mixins/__init__.py` | Mixin exports | ~20 |
| `mixins/cost_tracking_mixin.py` | Cost tracking | ~150 |
| `mixins/execution_logging_mixin.py` | Execution logging | ~250 |
| `mixins/validation_mixin.py` | Validation logic | ~400 |
| `mixins/http_handler_mixin.py` | HTTP operations | ~200 |
| `mixins/event_publisher_mixin.py` | Pub/Sub events | ~100 |
| `mixins/config_mixin.py` | Configuration | ~200 |
| `routes/__init__.py` | Route registration | ~30 |
| `routes/health.py` | Health endpoint | ~50 |
| `routes/scraper.py` | Scrape endpoint | ~100 |
| `routes/orchestration.py` | Workflow endpoints | ~150 |
| `routes/catchup.py` | Catchup endpoint | ~200 |
| `routes/cleanup.py` | Cleanup endpoint | ~100 |
| `routes/schedule_fix.py` | Schedule fix | ~100 |
| `services/orchestration_loader.py` | Lazy loading | ~100 |

---

## Inheritance Chain After Refactor

```
ScraperBase (with mixins)
├── NBAScraperBase
│   ├── BDLStandingsScraper
│   ├── ESPNScoreboardScraper
│   └── ... (all NBA scrapers)
└── MLBScraperBase
    └── ... (all MLB scrapers)
```

---

## Notes

- Mixins should be stateless or use `self._` prefixed attributes
- Order of mixin inheritance matters for method resolution
- Test at least one scraper from each sport after changes
- The `run()` method should remain in ScraperBase as the main orchestrator
