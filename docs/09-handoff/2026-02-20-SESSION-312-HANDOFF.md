# Session 312 Handoff — Best Bets 0-Pick Day Frontend Communication

**Date:** 2026-02-20
**Focus:** Make best bets JSON self-documenting on 0-pick days by exposing filter tracking, edge distribution, and metadata regardless of pick count
**Project docs:** `docs/08-projects/current/best-bets-v2/`

---

## What Was Done

### Problem

On Feb 20, the pipeline produced 694 predictions across 13 models for 9 games, but only 2 passed the edge >= 5.0 floor. Both were eliminated by downstream negative filters. The exported JSON showed `picks: []` with no explanation — the frontend had no way to communicate WHY there were 0 picks, making it look like a pipeline failure rather than an honest outcome.

### 5 Changes Implemented

### 1. Aggregator Filter Tracking (`ml/signals/aggregator.py`)

Changed `BestBetsAggregator.aggregate()` return type from `List[Dict]` to `Tuple[List[Dict], Dict]`. The second element is a `filter_summary` dict:

```python
filter_summary = {
    'total_candidates': 694,      # predictions entering the aggregator
    'passed_filters': 0,          # picks surviving all filters
    'rejected': {
        'blacklist': 0,
        'edge_floor': 692,        # < 5.0 edge
        'under_edge_7plus': 0,
        'familiar_matchup': 0,
        'quality_floor': 1,
        'bench_under': 0,
        'line_jumped_under': 0,
        'line_dropped_under': 0,
        'neg_pm_streak': 0,
        'signal_count': 0,
        'confidence': 0,
        'anti_pattern': 1,
    },
}
```

All 12 negative filters are tracked by name. A prediction is counted against the FIRST filter that rejects it (filters are applied in order).

### 2. 0-Prediction Metadata (`data_processors/publishing/signal_best_bets_exporter.py`)

The exporter had an early return path when `predictions == 0` that skipped computing signal_health, direction_health, player_blacklist, and record. These are now computed BEFORE the early return, so the JSON always includes:

- `signal_health` — per-signal regime (HOT/NORMAL/COLD)
- `direction_health` — OVER/UNDER hit rates
- `player_blacklist` — count and player list
- `record` — overall W-L record
- `filter_summary` — with zeroed counters on the 0-prediction path
- `edge_distribution` — with zeroed counters on the 0-prediction path

On the normal (predictions > 0) path, `edge_distribution` is newly computed before aggregation:

```python
edge_distribution = {
    'total_predictions': 694,
    'edge_3_plus': 47,
    'edge_5_plus': 2,
    'edge_7_plus': 0,
    'max_edge': 5.8,
}
```

Both paths (0-prediction early return and normal flow) now produce structurally identical JSON output.

### 3. Status.json Best Bets Service (`data_processors/publishing/status_exporter.py`)

Added `_check_best_bets_status()` method. Reads `v1/signal-best-bets/latest.json` from GCS and reports:

- **Freshness:** was the file updated today (ET timezone)?
- **Pick count:** extracted from the JSON's `total_picks` field
- **Status logic:**
  - 0 picks + fresh file = `healthy` with message "0 picks today — all candidates filtered out"
  - Stale file (not updated today) = `degraded` with staleness date
  - Schedule break active = `healthy` with break headline
  - File not found = `degraded`

The best_bets service is **excluded from `overall_status`** computation (line 92-97). Only live_data, tonight_data, and predictions feed into the overall health. This is intentional: 0 picks is an honest market outcome, not a system failure.

Stale best bets still surface in `known_issues` (via the generic `_build_known_issues` method that flags any degraded service).

### 4. Updated All Callers for Tuple Return

All call sites of `aggregator.aggregate()` updated to unpack the tuple:

| File | Change |
|------|--------|
| `ml/analysis/steering_replay.py` | `top_picks, _ = aggregator.aggregate(...)` |
| `data_processors/publishing/signal_annotator.py` | `top_picks, _ = aggregator.aggregate(...)` |
| `ml/experiments/signal_backtest.py` | `picks, _ = aggregator.aggregate(...)` |
| `ml/experiments/signal_backfill.py` | `top_picks, _ = aggregator.aggregate(...)` |
| `tests/unit/signals/test_player_blacklist.py` | `picks, _ = aggregator.aggregate(...)` (8 call sites) |

### 5. New Tests

**`tests/unit/signals/test_aggregator.py`** — 15 tests:
- `TestAggregatorReturnType` (2): verifies tuple return and empty-prediction summary structure
- `TestFilterTracking` (11): one test per filter (blacklist, edge_floor, under_edge_7plus, familiar_matchup, quality_floor, bench_under, line_jumped_under, line_dropped_under, neg_pm_streak, signal_count) plus total_candidates and passed_filters correctness
- `TestMultipleFilters` (2): mixed rejections and correct pick-through count

**`tests/unit/publishing/test_signal_best_bets_exporter.py`** — 12 tests:
- `TestZeroPredictionPath` (8): verifies 0-prediction JSON has record, signal_health, direction_health, player_blacklist, min_signal_count, filter_summary, edge_distribution, picks/total
- `TestStatusExporterBestBets` (4): verifies best_bets appears in services, 0 picks does not degrade overall_status, stale file surfaces in known_issues, break handling

All 27 new tests pass. Total test suite: 56 pass, 1 pre-existing failure.

---

## Files Changed

| File | Change |
|------|--------|
| `ml/signals/aggregator.py` | Return `Tuple[List[Dict], Dict]` with filter_summary; track all 12 filter rejections |
| `data_processors/publishing/signal_best_bets_exporter.py` | Compute metadata before early return; add filter_summary + edge_distribution to JSON output |
| `data_processors/publishing/status_exporter.py` | New `_check_best_bets_status()` method; best_bets in services dict; excluded from overall_status |
| `ml/analysis/steering_replay.py` | Tuple unpack for aggregate() call |
| `data_processors/publishing/signal_annotator.py` | Tuple unpack for aggregate() call |
| `ml/experiments/signal_backtest.py` | Tuple unpack for aggregate() call |
| `ml/experiments/signal_backfill.py` | Tuple unpack for aggregate() call |
| `tests/unit/signals/test_player_blacklist.py` | Tuple unpack for all 8 aggregate() calls |
| `tests/unit/signals/test_aggregator.py` | NEW — 15 tests for filter tracking |
| `tests/unit/publishing/test_signal_best_bets_exporter.py` | NEW — 12 tests for 0-pick metadata + status exporter |

---

## Verification Checklist for Next Session

### Priority 1: Confirm filter_summary appears in GCS export

```bash
# Check today's best bets JSON for the new fields
gsutil cat gs://nba-props-platform-api/v1/signal-best-bets/latest.json | python -m json.tool | grep -A 20 'filter_summary'
gsutil cat gs://nba-props-platform-api/v1/signal-best-bets/latest.json | python -m json.tool | grep -A 10 'edge_distribution'
```

**Expected:** Both `filter_summary` and `edge_distribution` present, even if `total_picks: 0`.

### Priority 2: Verify status.json includes best_bets service

```bash
gsutil cat gs://nba-props-platform-api/v1/status.json | python -m json.tool | grep -A 10 'best_bets'
```

**Expected:** `best_bets` key under `services` with `status`, `message`, `total_picks`, `last_update`.

### Priority 3: Verify best_bets does NOT affect overall_status

```bash
# Even if best_bets is degraded (stale), overall should NOT degrade just from that
gsutil cat gs://nba-props-platform-api/v1/status.json | python -m json.tool | grep 'overall_status'
```

### Priority 4: Run the full test suite

```bash
python -m pytest tests/unit/signals/test_aggregator.py tests/unit/publishing/test_signal_best_bets_exporter.py -v
```

**Expected:** 27 pass, 0 fail.

### Priority 5: Check deployment

```bash
./bin/check-deployment-drift.sh --verbose
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5
```

---

## Known Issues

| Issue | Status | Impact |
|-------|--------|--------|
| Pre-existing test failure: `test_algorithm_version_updated` | Stale `ALGORITHM_VERSION` assertion | 1 test fails; not related to this session's changes. The test asserts a specific version string that needs updating after a prior session changed the algorithm version. |
| 0 picks on Feb 20 | Expected behavior | Only 2 of 694 predictions had edge >= 5.0; both filtered by downstream negative filters. The new metadata makes this visible. |
| All models overdue for retrain | Blocked by ASB grading gap | Earliest retrain ~Feb 26 when post-break grading data accumulates |

---

## What NOT to Do

- Do NOT lower the edge floor (MIN_EDGE=5.0) to generate more picks — low-edge picks lose money
- Do NOT include best_bets in overall_status computation — 0 picks is honest, not a failure
- Do NOT remove the early return in signal_best_bets_exporter.py when predictions=0 — it still correctly short-circuits expensive signal evaluation
- Do NOT add filter_summary fields that don't correspond to actual aggregator filters — keep the two in sync

---

## Frontend Integration Notes

The JSON now supports three frontend states:

1. **Picks available** (`total_picks > 0`): Show picks as usual
2. **0 picks, data fresh** (`total_picks == 0, filter_summary present`): Show "No best bets today" with explanation from filter_summary (e.g., "694 candidates, 692 below edge floor, 1 quality filtered, 1 anti-pattern blocked")
3. **Stale data** (`status.json best_bets.status == 'degraded'`): Show "Data may be stale" warning

The `edge_distribution` field helps the frontend communicate market conditions: "Only 2 of 694 predictions had strong enough model confidence (edge 5+) today."
