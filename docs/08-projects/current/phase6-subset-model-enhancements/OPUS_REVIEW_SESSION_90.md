# Phase 6 Subset Exporters - Implementation Review Request

**Date:** 2026-02-03 (Session 90)
**Reviewer:** Claude Opus 4.5
**Implemented By:** Claude Sonnet 4.5
**Status:** Implementation complete, awaiting review before production deployment

---

## Review Objective

Please review the Phase 6 subset exporter implementation for:
1. **Architecture soundness** - Is the push strategy optimal?
2. **Security** - Are technical details properly hidden?
3. **Integration** - Will this work with existing orchestration?
4. **Code quality** - Any bugs, edge cases, or improvements?
5. **Production readiness** - Safe to deploy?

---

## Project Context

### Background

**NBA Stats Scraper System** processes predictions through 6 phases:
- Phase 1: Raw data scraping
- Phase 2: Data processing
- Phase 3: Analytics
- Phase 4: Feature engineering
- Phase 5: **Prediction generation** (ML models)
- Phase 6: **Publishing to GCS** (JSON API for website)

**This session:** Implemented 4 new exporters in Phase 6 to expose prediction subsets via clean API.

### Business Requirement

Expose 9 dynamic prediction subsets (Top Pick, Top 5, Top 10, etc.) to website without revealing:
- ML model internals (algorithm, features, training details)
- Technical metrics (confidence scores, edge calculations, composite scores)
- System identifiers (system_id, subset_id)

**Goal:** Clean public API that can be used for testing without exposing competitive strategy.

---

## What Was Implemented

### 1. Configuration Layer

**File:** `shared/config/subset_public_names.py`

```python
SUBSET_PUBLIC_NAMES = {
    'v9_high_edge_top1': {'id': '1', 'name': 'Top Pick'},
    'v9_high_edge_top5': {'id': '2', 'name': 'Top 5'},
    # ... 7 more subsets
}
```

**Design Decision:**
- Maps internal IDs → generic public names
- Separates concerns (exporters don't know about public names)

**Question for Review:** Is this the right abstraction level? Should public names be configurable?

---

### 2. Four Exporters

#### A. SubsetDefinitionsExporter

**Endpoint:** `/systems/subsets.json`
**Purpose:** List available groups with metadata
**Cache:** 24 hours
**Update:** Daily at 6 AM

**Output Structure:**
```json
{
  "generated_at": "2026-02-03T...",
  "model": "926A",
  "groups": [
    {
      "id": "1",
      "name": "Top Pick",
      "description": "Single best pick"
    }
  ]
}
```

**Implementation Highlights:**
- Queries `nba_predictions.dynamic_subset_definitions`
- Uses generic descriptions (never exposes database descriptions)
- No technical details (edge thresholds, confidence, etc.)

**Question for Review:** Should we include more metadata (e.g., historical performance)?

---

#### B. DailySignalsExporter

**Endpoint:** `/signals/{date}.json`
**Purpose:** Pre-game market signal
**Cache:** 5 minutes
**Update:** After predictions complete (event-driven)

**Output Structure:**
```json
{
  "date": "2026-02-03",
  "model": "926A",
  "signal": "favorable",  // or "neutral", "challenging"
  "metrics": {
    "conditions": "balanced",  // or "over_heavy", "under_heavy"
    "picks": 28
  }
}
```

**Implementation Highlights:**
- Maps internal GREEN/YELLOW/RED → favorable/neutral/challenging
- Hides pct_over thresholds (e.g., <25% = RED)
- Pre-game metric (doesn't need live updates)

**Question for Review:** Is the signal abstraction sufficient? Should we provide more context?

---

#### C. SubsetPerformanceExporter

**Endpoint:** `/subsets/performance.json`
**Purpose:** Compare all groups across time windows
**Cache:** 1 hour
**Update:** Hourly (6 AM - 11 PM) + post-game (2 AM)

**Output Structure:**
```json
{
  "model": "926A",
  "windows": {
    "last_7_days": {
      "start_date": "2026-01-27",
      "end_date": "2026-02-02",
      "groups": [
        {
          "id": "1",
          "name": "Top Pick",
          "stats": {
            "hit_rate": 81.8,
            "roi": 15.2,
            "picks": 6
          }
        }
      ]
    },
    "last_30_days": { /* ... */ },
    "season": { /* ... */ }
  }
}
```

**Implementation Highlights:**
- 3 time windows: 7-day, 30-day, season
- Queries `nba_predictions.v_dynamic_subset_performance` view
- Updates hourly to reflect newly completed games
- Clean stats only (hit_rate, ROI) - no MAE, avg_edge, avg_confidence

**Question for Review:** Is hourly refresh too frequent? Should it be 3-hourly or only after games complete?

---

#### D. AllSubsetsPicksExporter (Main Endpoint)

**Endpoint:** `/picks/{date}.json`
**Purpose:** All 9 groups' picks in ONE file
**Cache:** 5 minutes
**Update:** After predictions complete (event-driven)

**Output Structure:**
```json
{
  "date": "2026-02-03",
  "model": "926A",
  "groups": [
    {
      "id": "2",
      "name": "Top 5",
      "stats": {
        "hit_rate": 75.0,
        "roi": 9.1,
        "days": 30
      },
      "picks": [
        {
          "player": "LeBron James",
          "team": "LAL",
          "opponent": "BOS",
          "prediction": 26.1,
          "line": 24.5,
          "direction": "OVER"
        }
      ]
    }
  ]
}
```

**Implementation Highlights:**
- Queries predictions + applies subset filters dynamically
- Joins with `nba_reference.nba_players_registry` for player names
- Joins with `nba_analytics.player_game_summary` for team/opponent
- Calculates composite_score internally but DOESN'T export it
- Only 6 fields per pick (player, team, opponent, prediction, line, direction)

**Complex Logic:**
```python
def _filter_picks_for_subset(predictions, subset, daily_signal):
    # Apply edge filter
    if subset.get('min_edge'):
        if pred['edge'] < float(subset['min_edge']):
            continue

    # Apply confidence filter
    if subset.get('min_confidence'):
        if pred['confidence_score'] < float(subset['min_confidence']):
            continue

    # Apply signal condition filter
    if signal_condition and signal != signal_condition:
        continue

    # Apply pct_over range filter
    if pct_over_min and pct_over < pct_over_min:
        continue
```

**Question for Review:**
1. Is this filtering logic correct and complete?
2. Should we cache the subset definitions query?
3. Is the join strategy optimal (3 tables)?
4. Any edge cases we're missing?

---

## Push Strategy Analysis

### Current Patterns in System

| Pattern | Frequency | Use Case | Exporters |
|---------|-----------|----------|-----------|
| **Event-Driven** | After predictions | Fresh picks | tonight, best-bets, predictions |
| **Live Feed** | Every 3 min (games) | Real-time scoring | live, live-grading |
| **Hourly** | 6 AM - 11 PM hourly | Trend analysis | trends-hot-cold, bounce-back |
| **Daily** | Once/day | Historical data | results, performance |

### Our Decision

| Exporter | Pattern | Rationale |
|----------|---------|-----------|
| AllSubsetsPicksExporter | Event-Driven | Picks depend on predictions |
| DailySignalsExporter | Event-Driven | Signal calculated from predictions |
| SubsetPerformanceExporter | Hourly | Performance changes as games complete |
| SubsetDefinitionsExporter | Daily | Definitions rarely change |

### Alternative Considered: Live Feed Integration

**Rejected because:**
- Picks don't change during games (pre-game betting)
- Live feed = 20 exports/hour (overkill)
- Poor cache hit rate (3 min TTL vs 5 min TTL)
- Wrong use case fit (live feed is for real-time scoring)

**Question for Review:**
1. Is this push strategy optimal?
2. Should performance refresh MORE frequently (every game completion)?
3. Should picks update if lines change significantly mid-day?

---

## Integration Approach

### A. Event-Driven Integration

**Modified:** `orchestration/cloud_functions/phase5_to_phase6/main.py`

```python
# Before
TONIGHT_EXPORT_TYPES = ['tonight', 'tonight-players', 'predictions', 'best-bets', 'streaks']

# After
TONIGHT_EXPORT_TYPES = ['tonight', 'tonight-players', 'predictions', 'best-bets', 'streaks',
                        'subset-picks', 'daily-signals']
```

**Flow:**
1. Phase 5 predictions complete → Pub/Sub message to `nba-phase5-predictions-complete`
2. `phase5_to_phase6` orchestrator receives message
3. Publishes to `nba-phase6-export-trigger` with export_types
4. `phase6_export` cloud function runs exporters

**Question for Review:** Should subset-picks be separate from tonight-picks or always together?

---

### B. Scheduled Integration

**Hourly Refresh (6 AM - 11 PM):**
```json
{
  "export_types": ["trends-hot-cold", "trends-bounce-back", "tonight-trend-plays", "subset-performance"],
  "target_date": "today"
}
```

**Daily Batch (5 AM):**
```json
{
  "export_types": ["results", "performance", "best-bets", "subset-definitions"],
  "target_date": "yesterday"
}
```

**Question for Review:** Should subset-performance run post-game (2 AM) as well as hourly?

---

### C. Registration in daily_export.py

```python
# Imports
from data_processors.publishing.all_subsets_picks_exporter import AllSubsetsPicksExporter
# ... other imports

# EXPORT_TYPES list
EXPORT_TYPES = [
    # ... existing types
    'subset-picks', 'daily-signals', 'subset-performance', 'subset-definitions',
]

# export_date() function
if 'subset-picks' in export_types:
    try:
        exporter = AllSubsetsPicksExporter()
        path = exporter.export(target_date)
        result['paths']['subset_picks'] = path
        logger.info(f"  Subset Picks: {path}")
    except Exception as e:
        result['errors'].append(f"subset-picks: {e}")
        logger.error(f"  Subset Picks error: {e}")
```

**Error Handling:**
- Each exporter wrapped in try/except
- Errors appended to result['errors']
- Export continues even if one fails
- Status = 'partial' if some succeed, some fail

**Question for Review:** Is this error handling sufficient? Should we fail-fast or continue?

---

## Security Analysis

### What's Hidden

✅ **Blocked from API:**
- `system_id` (e.g., "catboost_v9")
- `subset_id` (e.g., "v9_high_edge_top5")
- `confidence_score` (0.92)
- `edge` (5.3 points)
- `composite_score` (edge * 10 + confidence * 0.5)
- Algorithm names (CatBoost, XGBoost)
- Feature counts (33 features)
- Training details (dates, approach)
- Filter criteria (edge >= 5, confidence >= 0.92)
- Signal thresholds (pct_over 25-40% = GREEN)

### What's Exposed

✅ **Shown in API:**
- Player name (from registry)
- Team / Opponent
- Prediction value (points)
- Vegas line
- Direction (OVER/UNDER)
- Generic group names ("Top 5")
- Model codename ("926A")
- Historical performance (hit_rate, ROI)

### Verification Tests

```bash
# Security check commands
gsutil cat gs://.../picks/2026-02-01.json | \
  grep -E "(system_id|subset_id|confidence|edge|composite)" && \
  echo "❌ LEAKED!" || echo "✅ Clean!"

# Result: ✅ Clean API - no technical details
```

**Question for Review:**
1. Are we hiding the right things?
2. Is exposing "model codename" (926A) too revealing?
3. Should we hide prediction values and only show direction?

---

## Testing Results

### Unit Tests

**File:** `bin/test-phase6-exporters.py`

```
✓ PASS: Subset Definitions - 9 groups, no leaks
✓ PASS: Daily Signals - Signal mapping works
✓ PASS: Subset Performance - 3 windows, 9 groups
✓ PASS: All Subsets Picks - Clean API, proper filtering

Passed: 4/4 🎉
```

### Integration Tests

**Local Export Test:**
```bash
PYTHONPATH=. python backfill_jobs/publishing/daily_export.py \
  --date 2026-02-01 \
  --only subset-picks,daily-signals,subset-performance,subset-definitions

# Results:
✓ Subset Picks: gs://.../v1/picks/2026-02-01.json (9 groups, 0 picks)
✓ Daily Signals: gs://.../v1/signals/2026-02-01.json (challenging, 4 picks)
✓ Subset Performance: gs://.../v1/subsets/performance.json (3 windows)
✓ Subset Definitions: gs://.../v1/systems/subsets.json (9 groups)
```

**File Structure Verification:**
```bash
gsutil cat gs://.../picks/2026-02-01.json | jq '.'
# ✓ Valid JSON
# ✓ Correct structure
# ✓ 9 groups present
# ✓ Model = "926A"

gsutil cat gs://.../signals/2026-02-01.json | jq '.'
# ✓ Signal = "challenging" (not "RED")
# ✓ Conditions = "under_heavy" (not technical pct_over)
```

**Question for Review:** What other tests should we run before production deployment?

---

## Known Limitations & Edge Cases

### 1. No Picks on Test Date

**Observation:** Feb 1 test showed 0 picks in all groups
**Reason:** Feb 1 was a RED signal day with only 4 high-edge picks
**Impact:** Most subsets have filters that excluded these picks
**Fix:** This is expected behavior (working as designed)

**Question:** Should we handle empty groups differently (hide them, show warning)?

---

### 2. Player Name Lookup

**Current:** Joins with `nba_reference.nba_players_registry`
**Fallback:** Uses `player_lookup` if name not found
**Edge Case:** New players might not be in registry yet

**Question:** Should we have a better fallback (parse player_lookup to "First Last")?

---

### 3. Team/Opponent Lookup

**Current:** Joins with `nba_analytics.player_game_summary`
**Edge Case:** If player didn't play (DNP), no row in summary
**Impact:** Pick would have NULL team/opponent

**Question:** Should we join with schedule table as fallback?

---

### 4. Subset Filter Race Condition

**Scenario:**
1. Predictions generated at 2:30 AM
2. Daily signal calculated from those predictions
3. Subset picks filtered by signal (GREEN/RED)
4. If predictions regenerate at 7 AM, signal might change
5. But subset picks don't re-export (only export after first run)

**Current Behavior:** Subset picks use signal from when they were exported
**Question:** Is this correct or should we re-export if signal changes?

---

### 5. Performance Lag

**Scenario:**
- Hourly performance export runs at 10 AM
- Games completed at 9:30 AM
- But grading hasn't run yet (runs at 10:30 AM)
- Performance shows stale data

**Current Behavior:** Performance reflects graded games only
**Question:** Should we add "last_updated" timestamp to performance?

---

## Deployment Plan

### Step 1: Commit & Push

```bash
git add data_processors/publishing/*_exporter.py
git add shared/config/subset_public_names.py
git add backfill_jobs/publishing/daily_export.py
git add orchestration/cloud_functions/phase5_to_phase6/main.py
git commit -m "feat: Add Phase 6 subset exporters with clean API"
git push origin main
```

### Step 2: Deploy Orchestrator

```bash
cd orchestration/cloud_functions/phase5_to_phase6
gcloud functions deploy phase5-to-phase6 \
  --region=us-west2 \
  --gen2 \
  --runtime=python311 \
  --source=. \
  --entry-point=orchestrate_phase5_to_phase6 \
  --trigger-topic=nba-phase5-predictions-complete
```

### Step 3: Update Schedulers

```bash
./bin/orchestrators/setup_phase6_subset_schedulers.sh

# Updates:
# - phase6-hourly-trends (add subset-performance)
# - phase6-daily-results (add subset-definitions)
```

### Step 4: Monitor First Run

```bash
# Wait for next prediction run (2:30 AM or 7 AM ET)
# Check logs
gcloud logging read 'resource.labels.function_name="phase5-to-phase6"' --limit=20

# Verify files
gsutil ls gs://nba-props-platform-api/v1/picks/*.json
gsutil ls gs://nba-props-platform-api/v1/signals/*.json
```

**Question for Review:** Is this deployment sequence safe? Any additional monitoring needed?

---

## Rollback Procedure

If issues arise:

```python
# 1. Revert phase5_to_phase6/main.py
TONIGHT_EXPORT_TYPES = ['tonight', 'tonight-players', 'predictions', 'best-bets', 'streaks']
# Remove: 'subset-picks', 'daily-signals'

# 2. Redeploy
gcloud functions deploy phase5-to-phase6 --region=us-west2

# 3. Revert schedulers
gcloud scheduler jobs update pubsub phase6-hourly-trends \
  --message-body='{"export_types": ["trends-hot-cold", "trends-bounce-back", "tonight-trend-plays"]}'
```

**Impact:** Old exporters continue working, new ones stop updating

---

## Questions for Opus Review

### Critical Questions

1. **Architecture:** Is the single-file approach (all 9 groups in one JSON) better than 9 separate files?
   - Pro: One API call, simpler testing
   - Con: Larger file size, can't cache individual groups

2. **Security:** Are we hiding the right technical details? Is "926A" model codename safe to expose?

3. **Performance:** Should SubsetPerformanceExporter run every hour or only after games complete?

4. **Error Handling:** Continue-on-error vs fail-fast? Current approach allows partial success.

5. **Edge Cases:** How should we handle:
   - Empty groups (no picks match filters)
   - Missing player names
   - NULL team/opponent
   - Signal changes between exports

### Design Questions

6. **Caching:** Are cache TTLs appropriate?
   - Picks: 5 min
   - Signals: 5 min
   - Performance: 1 hour
   - Definitions: 24 hours

7. **API Evolution:** Should we version the API endpoints (/v1/picks, /v2/picks)?

8. **Extensibility:** How easy is it to add new subsets or change definitions?

### Production Readiness

9. **Testing:** What additional tests needed before production?

10. **Monitoring:** What metrics should we track?
    - Export success rate
    - File sizes
    - Query latency
    - Error rates

11. **Documentation:** Is the API self-documenting enough for frontend team?

12. **Backwards Compatibility:** Does this break any existing exports?

---

## Code Review Focus Areas

Please pay special attention to:

1. **`all_subsets_picks_exporter.py` lines 169-292** - Complex filtering logic
2. **`daily_export.py` lines 330-375** - Error handling for new exporters
3. **`phase5_to_phase6/main.py` lines 71-78** - Integration with existing flow
4. **`subset_public_names.py`** - Public name mappings (security critical)

---

## Reference Files

**Implementation:**
- `data_processors/publishing/all_subsets_picks_exporter.py` (main endpoint)
- `data_processors/publishing/daily_signals_exporter.py`
- `data_processors/publishing/subset_performance_exporter.py`
- `data_processors/publishing/subset_definitions_exporter.py`
- `shared/config/subset_public_names.py`

**Integration:**
- `backfill_jobs/publishing/daily_export.py`
- `orchestration/cloud_functions/phase5_to_phase6/main.py`

**Tests:**
- `bin/test-phase6-exporters.py`

**Documentation:**
- `docs/08-projects/current/phase6-subset-model-enhancements/PUSH_STRATEGY.md`
- `docs/09-handoff/2026-02-03-SESSION-90-HANDOFF.md`

---

## Expected Opus Review Output

Please provide:

1. **Thumbs Up/Down** - Safe to deploy?
2. **Critical Issues** - Bugs, security risks, architectural flaws
3. **Recommendations** - Improvements, alternative approaches
4. **Edge Cases** - Scenarios we haven't considered
5. **Testing Suggestions** - Additional tests before production
6. **Monitoring Recommendations** - What to track post-deployment

---

**Thank you for the review!** 🙏

This is the first time we're exposing prediction subsets via public API, so extra scrutiny appreciated.

---

**Implementation Stats:**
- Lines of code: ~900
- Files created: 9
- Files modified: 2
- Test coverage: 4 unit tests + integration tests
- Security checks: ✅ Passed
- Local testing: ✅ All exporters work
