# Scraper Reliability Fixes - January 30, 2026

## Executive Summary

A 7-day outage of the workflow orchestration system (Jan 23-30, 2026) revealed **four systemic issues** in the scraper infrastructure. This project documents the root causes and implements comprehensive fixes to prevent recurrence.

### Impact of the Outage
- **Duration**: 169 hours (Jan 23 20:07 UTC - Jan 30 08:34 UTC)
- **Data Loss**: Jan 29 box scores not collected (8 games, ~250 players)
- **Root Cause**: Missing f-string prefix in `workflow_executor.py` line 252

### Issues Discovered

| Issue | Severity | Status |
|-------|----------|--------|
| [1. Parameter Naming Chaos](#issue-1-parameter-naming-chaos) | HIGH | TODO |
| [2. Execution Logging False Negatives](#issue-2-execution-logging-false-negatives) | HIGH | TODO |
| [3. Missing Testing & Monitoring](#issue-3-missing-testing--monitoring) | CRITICAL | TODO |
| [4. Gap Backfiller Design Flaw](#issue-4-gap-backfiller-design-flaw) | HIGH | TODO |

---

## Issue 1: Parameter Naming Chaos

### Problem Statement

Three different naming conventions exist for date parameters with no enforced standard:

| Convention | Used By | Format | Example Scrapers |
|------------|---------|--------|------------------|
| `date` | BettingPros, Ball Don't Lie | YYYY-MM-DD | `bp_events.py`, `bdl_box_scores.py` |
| `gamedate` | NBA.com scrapers | YYYYMMDD | `nbac_player_boxscore.py`, `nbac_play_by_play.py` |
| `game_date` | Odds API scrapers | YYYY-MM-DD | `oddsa_events.py`, `oddsa_player_props.py` |

### Root Cause

- Organic growth without documented standards
- Different scraper families developed at different times by different authors
- `parameter_resolver.py` **masks** the inconsistency with custom resolvers instead of enforcing standards

### Impact

- Gap backfiller calls scrapers with `date` but NBA.com scrapers need `gamedate`
- Developers must memorize parameter names per scraper
- No compile-time or runtime validation catches mismatches
- Error messages ("Missing required option [gamedate]") don't suggest alternatives

### Evidence

```python
# Gap backfiller (WRONG):
response = requests.post(url, json={"scraper": "nbac_player_boxscore", "date": "2026-01-29"})

# Scraper requirement:
required_params = ["gamedate"]  # Not "date"!
```

### Files Involved

- `orchestration/cloud_functions/scraper_gap_backfiller/main.py` (lines 222-230, 247-251)
- `scrapers/nbacom/nbac_player_boxscore.py` (line 73)
- `scrapers/nbacom/nbac_play_by_play.py` (line 64)
- `config/scraper_parameters.yaml`
- `orchestration/parameter_resolver.py`

### Fix Plan

1. Create centralized parameter registry (`shared/config/scraper_parameter_registry.yaml`)
2. Add pre-commit hook to validate scrapers match registry
3. Update gap backfiller to use parameter resolver
4. Document parameter conventions in developer guide

---

## Issue 2: Execution Logging False Negatives

### Problem Statement

Scrapers using `ExportMode.DECODED` report "no_data" even when data is successfully saved to GCS.

### Root Cause

The scraper framework has an implicit contract violation:

```
Data Flow:
1. API response → self.decoded_data (populated)
2. transform_data() → self.data (NOT CALLED - empty)
3. ExportMode.DECODED → exports self.decoded_data to GCS ✅
4. execution_logging_mixin → checks self.data → finds empty → reports "no_data" ❌
```

The `transform_data()` hook has an empty default implementation, so scrapers using `ExportMode.DECODED` don't realize they need to populate `self.data` for logging.

### Impact

- `nbac_player_boxscore` saves 203 players to GCS but reports "no_data"
- Orchestration thinks scraper failed, keeps retrying
- Discovery mode controller makes wrong decisions
- Potentially 1-5 other scrapers have this same bug

### Evidence

```bash
# Data exists in GCS:
gsutil cat "gs://nba-scraped-data/nba-com/player-boxscores/2026-01-28/20260129_110523.json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['resultSets'][0]['rowSet']), 'players')"
# Output: 203 players

# But orchestration reports:
# status = "no_data", record_count = 0
```

### Files Involved

- `scrapers/scraper_base.py` (lines 658-667 - export logic)
- `scrapers/mixins/execution_logging_mixin.py` (lines 141-204 - status determination)
- `scrapers/mixins/config_mixin.py` (lines 281-308 - empty transform_data)
- `scrapers/nbacom/nbac_player_boxscore.py` (missing transform_data)

### Fix Plan

1. **Option A (Recommended)**: Fix `execution_logging_mixin` to check `decoded_data` when `data` is empty
2. **Option B**: Add `transform_data()` to all scrapers using `ExportMode.DECODED`
3. Add pre-commit hook to warn when ExportMode.DECODED used without transform_data
4. Audit all 33 scrapers using ExportMode.DECODED

---

## Issue 3: Missing Testing & Monitoring

### Problem Statement

The f-string bug persisted for **7 days** because no tests or alerts caught it.

### Root Cause

Multiple gaps in the testing pyramid and monitoring stack:

| Layer | Gap |
|-------|-----|
| **Unit Tests** | `execute_pending_workflows()` not tested |
| **Integration Tests** | `/execute-workflows` endpoint not tested |
| **Query Validation** | No test that BigQuery queries are properly formatted |
| **Linting** | Ruff rules don't catch missing f-string prefixes |
| **Pre-commit** | No hook for SQL queries with uninterpolated variables |
| **Monitoring** | No alert for "zero workflows executed" |
| **Anomaly Detection** | No baseline comparison for workflow counts |

### Evidence

The bug was introduced in commit `efb858a7`:
```
feat: Add resilience improvements and test fixes
- 28 files changed, 341 insertions, 181 deletions
- Changed hardcoded project ID to {self.project_id}
- Forgot to add 'f' prefix
- Merged without catching the error
```

**Current linting configuration** (too permissive):
```yaml
# .github/workflows/test.yml
- name: Run ruff check
  run: ruff check --select=E9,F63,F7,F82 --output-format=github .
  continue-on-error: true  # ❌ Non-blocking!
```

### Files Involved

- `orchestration/workflow_executor.py` (line 252 - the bug)
- `tests/unit/orchestration/test_workflow_executor.py` (missing integration tests)
- `.github/workflows/test.yml` (weak linting)
- `.pre-commit-config.yaml` (missing SQL validation hook)
- `bin/monitoring/check_workflow_health.sh` (no zero-execution alert)

### Fix Plan

1. Add integration test for `execute_pending_workflows()`
2. Add endpoint test for `/execute-workflows`
3. Add pre-commit hook for SQL queries with `{self.` pattern
4. Make linting blocking in CI
5. Add "zero workflows executed" alert
6. Add anomaly detection for workflow execution counts

---

## Issue 4: Gap Backfiller Design Flaw

### Problem Statement

The gap backfiller Cloud Function doesn't use the parameter resolver, causing it to call scrapers with incorrect parameters.

### Root Cause

The gap backfiller was designed as a "simple, lightweight recovery tool" that assumes all scrapers have uniform parameters:

```python
# Current implementation (WRONG):
response = requests.post(
    f"{SCRAPER_SERVICE_URL}/scrape",
    json={"scraper": scraper_name, "date": test_date}
)
```

But scrapers have complex, scraper-specific requirements:
- NBA.com scrapers need `gamedate` (not `date`)
- Play-by-play scrapers need `game_id` (per-game)
- Odds scrapers need `event_ids` from upstream scrapers
- Post-game workflows target yesterday's date

### Impact

- Every 4 hours, gap backfiller triggers scrapers with wrong parameters
- Multi-entity scrapers (per-game, per-team) always fail
- Creates noise in logs and wastes resources
- `nbac_player_boxscore` and `nbac_play_by_play` fail every run

### Evidence

```sql
-- Scraper execution log shows MANUAL failures every 4 hours:
SELECT workflow, scraper_name, status, error_message
FROM nba_orchestration.scraper_execution_log
WHERE workflow = 'MANUAL' AND DATE(triggered_at) >= '2026-01-29'

-- Result:
-- MANUAL | nbac_player_boxscore | failed | Missing required option [gamedate].
-- MANUAL | nbac_play_by_play    | failed | Missing required option [game_id].
```

### Files Involved

- `orchestration/cloud_functions/scraper_gap_backfiller/main.py`
- `orchestration/parameter_resolver.py` (the correct way to resolve parameters)
- Cloud Scheduler: `scraper-gap-backfiller-schedule` (0 */4 * * *)

### Fix Plan

1. Integrate parameter resolver into gap backfiller
2. Handle multi-entity scrapers (per-game, per-team)
3. Support dependency chains (event_ids for odds scrapers)
4. Add parameter validation before calling scrapers
5. Add tests for gap backfiller parameter handling

---

## Action Plan

### Phase 1: Immediate Fixes (P0)

| Task | Priority | Effort | Owner |
|------|----------|--------|-------|
| Fix gap backfiller parameter passing | P0 | 2h | TBD |
| Add "zero workflows" alert | P0 | 1h | TBD |
| Fix nbac_player_boxscore transform_data | P0 | 30m | TBD |
| Trigger Jan 29 backfill | P0 | 30m | TBD |

### Phase 2: Prevention (P1)

| Task | Priority | Effort | Owner |
|------|----------|--------|-------|
| Add integration test for execute_pending_workflows | P1 | 2h | TBD |
| Add pre-commit hook for SQL f-strings | P1 | 1h | TBD |
| Make linting blocking in CI | P1 | 30m | TBD |
| Create parameter registry | P1 | 2h | TBD |

### Phase 3: Hardening (P2)

| Task | Priority | Effort | Owner |
|------|----------|--------|-------|
| Audit all ExportMode.DECODED scrapers | P2 | 2h | TBD |
| Add anomaly detection for workflow counts | P2 | 2h | TBD |
| Document parameter conventions | P2 | 1h | TBD |
| Add pre-commit hook for parameter registry | P2 | 2h | TBD |

---

## Related Documents

- [Session 29 Handoff](../../../09-handoff/2026-01-30-SESSION-29-HANDOFF.md) - Initial bug fix
- [Parameter Formats Reference](../../../archive/2025-08-14/reference/scrapers/2025-11-13-parameter-formats.md) - Historical documentation

---

## Timeline

- **2026-01-23 20:07 UTC**: Bug introduced (commit efb858a7)
- **2026-01-30 00:26 UTC**: Bug fixed (commit f08a5f0c)
- **2026-01-30 08:34 UTC**: Fix deployed
- **2026-01-30 08:44 UTC**: Investigation began
- **2026-01-30 XX:XX UTC**: Systemic fixes implemented

---

*Created: 2026-01-30*
*Last Updated: 2026-01-30*
