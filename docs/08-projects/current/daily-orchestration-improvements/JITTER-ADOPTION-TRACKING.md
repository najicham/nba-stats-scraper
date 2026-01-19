# Jitter Adoption & Connection Pooling - File Tracking

**Project:** Phase 3 - Retry & Connection Pooling
**Start Date:** January 19, 2026
**Status:** 🟡 In Progress
**Progress:** 0/76 files (0%)

---

## 📊 Progress Summary

| Category | Total Files | Completed | Remaining | % Complete |
|----------|-------------|-----------|-----------|------------|
| **Task 3.1.1** - Remove Duplicate Logic | 2 | 0 | 2 | 0% |
| **Task 3.1.2** - Replace batch_writer | 1 | 0 | 1 | 0% |
| **Task 3.1.3** - Jitter in Data Processors | 18 | 0 | 18 | 0% |
| **Task 3.2** - Jitter in Orchestration | 5 | 0 | 5 | 0% |
| **Task 3.3** - BigQuery Pooling | 30 | 0 | 30 | 0% |
| **Task 3.4** - HTTP Pooling | 20 | 0 | 20 | 0% |
| **TOTAL** | **76** | **0** | **76** | **0%** |

---

## ✅ Task 3.1.1: Remove Duplicate Serialization Logic (2 files)

### File 1: processor_base.py
- **Path:** `data_processors/raw/processor_base.py`
- **Status:** ⚪ Not Started
- **Lines to Remove:** 62-78 (`_is_serialization_conflict` function)
- **Import to Add:** `from shared.utils.bigquery_retry import is_serialization_error, SERIALIZATION_RETRY, QUOTA_RETRY`
- **Changes:**
  - [ ] Remove duplicate function
  - [ ] Add import from shared.utils.bigquery_retry
  - [ ] Replace usage in retry.Retry predicate
  - [ ] Test: `python3 -c "from data_processors.raw.processor_base import ProcessorBase; print('✓')"`

### File 2: nbac_gamebook_processor.py
- **Path:** `data_processors/raw/nbacom/nbac_gamebook_processor.py`
- **Status:** ⚪ Not Started
- **Lines to Remove:** 62-78 (`_is_serialization_conflict` function)
- **Import to Add:** `from shared.utils.bigquery_retry import is_serialization_error, SERIALIZATION_RETRY`
- **Changes:**
  - [ ] Remove duplicate function
  - [ ] Add import from shared.utils.bigquery_retry
  - [ ] Replace usage in retry.Retry predicate
  - [ ] Test: Import processor successfully

---

## ✅ Task 3.1.2: Replace batch_writer Manual Retry (1 file)

### File 3: batch_writer.py
- **Path:** `data_processors/precompute/ml_feature_store/batch_writer.py`
- **Status:** ⚪ Not Started
- **Lines to Modify:**
  - 32-34 (remove MAX_RETRIES, RETRY_DELAY_SECONDS)
  - 306-343 (replace load retry loop)
  - 417-441 (replace MERGE retry loop)
- **Import to Add:** `from shared.utils.bigquery_retry import SERIALIZATION_RETRY, QUOTA_RETRY`
- **Changes:**
  - [ ] Remove configuration constants (MAX_RETRIES, RETRY_DELAY_SECONDS)
  - [ ] Create `_load_to_temp_table_with_retry()` with @SERIALIZATION_RETRY
  - [ ] Create `_merge_to_target_with_retry()` with @QUOTA_RETRY + @SERIALIZATION_RETRY
  - [ ] Update callers to use new functions
  - [ ] Keep streaming buffer special case handling
  - [ ] Test: Import and verify no manual for-loops remain

---

## ✅ Task 3.1.3: Apply Jitter to Data Processors (18 files)

### Raw Processors (6 files)

#### File 4: espn_team_roster_processor.py
- **Path:** `data_processors/raw/espn/espn_team_roster_processor.py`
- **Status:** ⚪ Not Started
- **Pattern:** DELETE + INSERT operations
- **Changes:**
  - [ ] Add import: `from shared.utils.bigquery_retry import SERIALIZATION_RETRY`
  - [ ] Wrap DELETE operation (lines 320-325)
  - [ ] Wrap INSERT operation (lines 345-354)
  - [ ] Test: Verify operations work

#### File 5: br_roster_processor.py
- **Path:** `data_processors/raw/basketball_ref/br_roster_processor.py`
- **Status:** ⚪ Not Started
- **Pattern:** MERGE operation (already has decorators)
- **Changes:**
  - [ ] Verify existing @QUOTA_RETRY + @SERIALIZATION_RETRY usage
  - [ ] Ensure query submission is inside decorator (lines 369-375)
  - [ ] No changes needed if already correct

#### File 6: odds_game_lines_processor.py
- **Path:** `data_processors/raw/oddsapi/odds_game_lines_processor.py`
- **Status:** ⚪ Not Started
- **Pattern:** MERGE operation with streaming buffer handling
- **Changes:**
  - [ ] Verify @SERIALIZATION_RETRY usage (lines 611-616)
  - [ ] Ensure query submission inside decorator
  - [ ] Verify streaming buffer special case handling

#### File 7: bdl_player_boxscores_processor.py
- **Path:** `data_processors/raw/balldontlie/bdl_player_boxscores_processor.py`
- **Status:** ⚪ Not Started
- **Pattern:** To be determined (grep for query operations)
- **Changes:**
  - [ ] Find BigQuery write operations
  - [ ] Add @SERIALIZATION_RETRY decorator
  - [ ] Test operations

#### File 8: nbac_schedule_processor.py
- **Path:** `data_processors/raw/nbacom/nbac_schedule_processor.py`
- **Status:** ⚪ Not Started
- **Pattern:** To be determined
- **Changes:**
  - [ ] Find BigQuery write operations
  - [ ] Add @SERIALIZATION_RETRY decorator
  - [ ] Test operations

#### File 9: nbac_team_boxscore_processor.py
- **Path:** `data_processors/raw/nbacom/nbac_team_boxscore_processor.py`
- **Status:** ⚪ Not Started
- **Pattern:** To be determined
- **Changes:**
  - [ ] Find BigQuery write operations
  - [ ] Add @SERIALIZATION_RETRY decorator
  - [ ] Test operations

### Analytics Processors (5 files)

#### File 10: player_game_summary_processor.py
- **Path:** `data_processors/analytics/player_game_summary/player_game_summary_processor.py`
- **Status:** ⚪ Not Started
- **Pattern:** MERGE_UPDATE strategy
- **Changes:**
  - [ ] Find BigQuery MERGE operations
  - [ ] Add @SERIALIZATION_RETRY + @QUOTA_RETRY (high concurrency)
  - [ ] Test operations

#### File 11: team_defense_game_summary_processor.py
- **Path:** `data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py`
- **Status:** ⚪ Not Started
- **Pattern:** To be determined
- **Changes:**
  - [ ] Find BigQuery write operations
  - [ ] Add appropriate retry decorators
  - [ ] Test operations

#### File 12: team_offense_game_summary_processor.py
- **Path:** `data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py`
- **Status:** ⚪ Not Started
- **Pattern:** To be determined
- **Changes:**
  - [ ] Find BigQuery write operations
  - [ ] Add appropriate retry decorators
  - [ ] Test operations

#### File 13: upcoming_player_game_context_processor.py
- **Path:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`
- **Status:** ⚪ Not Started
- **Pattern:** To be determined
- **Changes:**
  - [ ] Find BigQuery write operations
  - [ ] Add appropriate retry decorators
  - [ ] Test operations

#### File 14: upcoming_team_game_context_processor.py
- **Path:** `data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py`
- **Status:** ⚪ Not Started
- **Pattern:** To be determined
- **Changes:**
  - [ ] Find BigQuery write operations
  - [ ] Add appropriate retry decorators
  - [ ] Test operations

### Precompute Processors (5 files)

#### File 15: ml_feature_store_processor.py
- **Path:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
- **Status:** ⚪ Not Started
- **Pattern:** Uses BatchWriter (handled in Task 3.1.2)
- **Changes:**
  - [ ] Verify BatchWriter integration works after Task 3.1.2
  - [ ] No direct changes needed (inherits from BatchWriter)

#### File 16: player_daily_cache_processor.py
- **Path:** `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
- **Status:** ⚪ Not Started
- **Pattern:** To be determined
- **Changes:**
  - [ ] Find BigQuery write operations
  - [ ] Add appropriate retry decorators
  - [ ] Test operations

#### File 17: player_composite_factors_processor.py
- **Path:** `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py`
- **Status:** ⚪ Not Started
- **Pattern:** To be determined
- **Changes:**
  - [ ] Find BigQuery write operations
  - [ ] Add appropriate retry decorators
  - [ ] Test operations

#### File 18: player_shot_zone_analysis_processor.py
- **Path:** `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py`
- **Status:** ⚪ Not Started
- **Pattern:** To be determined
- **Changes:**
  - [ ] Find BigQuery write operations
  - [ ] Add appropriate retry decorators
  - [ ] Test operations

#### File 19: team_defense_zone_analysis_processor.py
- **Path:** `data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py`
- **Status:** ⚪ Not Started
- **Pattern:** To be determined
- **Changes:**
  - [ ] Find BigQuery write operations
  - [ ] Add appropriate retry decorators
  - [ ] Test operations

### Grading Processors (2 files)

#### File 20: prediction_accuracy_processor.py
- **Path:** `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`
- **Status:** ⚪ Not Started
- **Pattern:** Uses distributed lock
- **Changes:**
  - [ ] Find BigQuery write operations (not lock operations)
  - [ ] Add appropriate retry decorators
  - [ ] Test operations

#### File 21: system_daily_performance_processor.py
- **Path:** `data_processors/grading/system_daily_performance/system_daily_performance_processor.py`
- **Status:** ⚪ Not Started
- **Pattern:** To be determined
- **Changes:**
  - [ ] Find BigQuery write operations
  - [ ] Add appropriate retry decorators
  - [ ] Test operations

---

## ✅ Task 3.2: Apply Jitter to Orchestration (5 files)

### File 22: self_heal/main.py
- **Path:** `orchestration/cloud_functions/self_heal/main.py`
- **Status:** ⚪ Not Started
- **Pattern:** BigQuery queries for self-healing logic
- **Changes:**
  - [ ] Add import: `from shared.utils.bigquery_retry import SERIALIZATION_RETRY`
  - [ ] Wrap BigQuery query operations
  - [ ] Test cloud function

### File 23: mlb_self_heal/main.py
- **Path:** `orchestration/cloud_functions/mlb_self_heal/main.py`
- **Status:** ⚪ Not Started
- **Pattern:** BigQuery queries for MLB self-healing
- **Changes:**
  - [ ] Add import: `from shared.utils.bigquery_retry import SERIALIZATION_RETRY`
  - [ ] Wrap BigQuery query operations
  - [ ] Test cloud function

### File 24: transition_monitor/main.py
- **Path:** `orchestration/cloud_functions/transition_monitor/main.py`
- **Status:** ⚪ Not Started
- **Pattern:** BigQuery queries for monitoring
- **Changes:**
  - [ ] Add import: `from shared.utils.bigquery_retry import SERIALIZATION_RETRY`
  - [ ] Wrap BigQuery query operations
  - [ ] Test cloud function

### File 25: grading/main.py
- **Path:** `orchestration/cloud_functions/grading/main.py`
- **Status:** ⚪ Not Started
- **Pattern:** Uses distributed lock + BigQuery queries
- **Changes:**
  - [ ] Add import: `from shared.utils.bigquery_retry import SERIALIZATION_RETRY`
  - [ ] Wrap BigQuery query operations (NOT distributed lock operations)
  - [ ] Test cloud function

### File 26: workflow_executor.py
- **Path:** `orchestration/workflow_executor.py`
- **Status:** ⚪ Not Started
- **Pattern:** HTTP retry (handled in Task 3.4)
- **Note:** HTTP pooling handled separately in Task 3.4

---

## ✅ Task 3.3: Integrate BigQuery Pooling (30 files)

### Base Classes (High Priority - 3 files)

#### File 27: processor_base.py (Raw)
- **Path:** `data_processors/raw/processor_base.py`
- **Status:** ⚪ Not Started
- **Changes:**
  - [ ] Replace: `from google.cloud import bigquery` → `from shared.clients.bigquery_pool import get_bigquery_client`
  - [ ] Replace: `self.bq_client = bigquery.Client(project=project_id)` → `self.bq_client = get_bigquery_client(project_id=project_id)`
  - [ ] Test: Verify child processors inherit pooled client

#### File 28: analytics_base.py
- **Path:** `data_processors/analytics/analytics_base.py`
- **Status:** ⚪ Not Started
- **Changes:**
  - [ ] Replace client instantiation with get_bigquery_client()
  - [ ] Test: Verify child processors inherit pooled client

#### File 29: precompute_base.py
- **Path:** `data_processors/precompute/precompute_base.py`
- **Status:** ⚪ Not Started
- **Changes:**
  - [ ] Replace client instantiation with get_bigquery_client()
  - [ ] Test: Verify child processors inherit pooled client

### Cloud Functions (10 files)

#### File 30-39: All Cloud Function main.py files
- **Paths:** `orchestration/cloud_functions/*/main.py`
- **Status:** ⚪ Not Started (each)
- **Changes per file:**
  - [ ] Replace bigquery.Client() with get_bigquery_client()
  - [ ] Test function deployment

**Files:**
1. phase2_to_phase3/main.py
2. phase3_to_phase4/main.py
3. phase4_to_phase5/main.py
4. daily_health_check/main.py
5. self_heal/main.py
6. mlb_self_heal/main.py
7. transition_monitor/main.py
8. grading/main.py
9. cleanup_processor/main.py
10. dlq_monitor/main.py

### Individual Processors (17 files)

**Note:** Many processors inherit from base classes (Files 27-29). After updating base classes, verify these processors automatically use pooling.

#### Files 40-56: Individual processor files
- **Status:** ⚪ Not Started (each)
- **Strategy:**
  - First update base classes (Files 27-29)
  - Then grep for any processors creating clients directly
  - Update only those that don't inherit from base classes

**Command to find:**
```bash
grep -r "bigquery\.Client(" data_processors/ --include="*.py" | grep -v "base.py" | grep -v "test"
```

---

## ✅ Task 3.4: Integrate HTTP Pooling (20 files)

### High Priority (1 file)

#### File 57: workflow_executor.py
- **Path:** `orchestration/workflow_executor.py`
- **Status:** ⚪ Not Started
- **Lines:** 533-701 (HTTP retry pattern)
- **Changes:**
  - [ ] Add import: `from shared.clients.http_pool import get_http_session`
  - [ ] Replace: `requests.post()` → `get_http_session().post()`
  - [ ] Keep existing timeout configuration
  - [ ] Test: Verify scraper calls work

### Scraper Files (19 files)

**Command to find:**
```bash
grep -r "requests\.get\|requests\.post\|requests\.Session" scrapers/ backfill_jobs/ --include="*.py" | cut -d: -f1 | sort -u
```

#### Files 58-76: Scraper HTTP calls
- **Status:** ⚪ Not Started (each)
- **Pattern:** Replace direct requests with pooled session
- **Changes per file:**
  - [ ] Add import: `from shared.clients.http_pool import get, post` (or `get_http_session`)
  - [ ] Replace: `requests.get(url)` → `get(url)`
  - [ ] Replace: `requests.post(url, json=data)` → `post(url, json=data)`
  - [ ] Test: Verify HTTP calls work

**Expected files:**
- scrapers/balldontlie/bdl_games_scraper.py
- scrapers/nbacom/nbac_gamebook_scraper.py
- scrapers/oddsapi/odds_game_lines_scraper.py
- scrapers/espn/espn_roster_scraper.py
- scrapers/basketball_ref/br_roster_scraper.py
- backfill_jobs/scrapers/* (multiple files)
- ~14 additional scraper files

---

## 📈 Progress Tracking Commands

### Check Progress
```bash
# Count completed files
grep -c "✅ Complete" docs/08-projects/current/daily-orchestration-improvements/JITTER-ADOPTION-TRACKING.md

# Find remaining bigquery.Client() calls
grep -r "bigquery\.Client(" data_processors/ orchestration/ --include="*.py" | wc -l

# Find remaining direct requests calls
grep -r "requests\.get\|requests\.post" scrapers/ orchestration/ --include="*.py" | grep -v "http_pool" | wc -l
```

### Verify Pooling Integration
```bash
# Verify BigQuery pooling usage
grep -r "get_bigquery_client" data_processors/ orchestration/ --include="*.py" | wc -l

# Verify HTTP pooling usage
grep -r "from shared.clients.http_pool import" scrapers/ orchestration/ --include="*.py" | wc -l
```

---

## 🎯 Weekly Milestones

### Week 1 (Jan 19-25)
- [ ] Complete Task 3.1 (21 files) - Jitter in data processors
- [ ] Complete Task 3.2 (5 files) - Jitter in orchestration
- **Target:** 26/76 files (34%)

### Week 2 (Jan 26 - Feb 1)
- [ ] Complete Task 3.3 (30 files) - BigQuery pooling
- [ ] Complete Task 3.4 (20 files) - HTTP pooling
- **Target:** 76/76 files (100%)

### Week 3 (Feb 2-8)
- [ ] Task 3.5: Performance testing
- [ ] Documentation updates
- [ ] Deploy to staging
- [ ] Production deployment

---

## ✅ File Update Template

When updating a file, use this checklist:

```markdown
### File X: filename.py
- **Path:** full/path/to/file.py
- **Status:** ✅ Complete | ⚠️ In Progress | ⚪ Not Started
- **Updated By:** Session ID
- **Date:** YYYY-MM-DD
- **Changes:**
  - [x] Added imports
  - [x] Applied retry decorators / connection pooling
  - [x] Tested locally
  - [x] Committed to git
- **Notes:** Any issues or special cases
```

---

**Last Updated:** January 19, 2026
**Session:** 119
**Next Review:** Check progress after 10 files completed
