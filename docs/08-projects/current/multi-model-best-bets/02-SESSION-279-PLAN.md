# Session 279: Pick Provenance & Hierarchical Layers

**Status:** PLAN — Review and implement
**Context:** Sessions 277-278 built 3-layer multi-model best bets + smart filters + pick angles. But the "layers" are actually 3 parallel tracks. This session wires them into a true hierarchy and adds full provenance.

---

## The Problem

The 3-layer architecture was labeled as layers but works as **3 parallel tracks**:

```
Raw Predictions (player_prop_predictions, 6 models)
    │
    ├── Track A: SubsetMaterializer ──────► Level 1 picks (per-model subsets)
    │                                        NOT used by anything downstream
    │
    ├── Track B: CrossModelSubsetMaterializer ► Level 2 picks (xm_* subsets)
    │     └── queries raw predictions directly   NOT used by anything downstream
    │
    └── Track C: BestBetsAggregator ──────► Level 3 picks (best bets top 5)
          └── queries raw predictions directly
          └── runs signals on raw predictions
          └── adds consensus_bonus from CrossModelScorer
              (which ALSO queries raw predictions directly)
```

**Result:** A best bet pick has no idea it also appeared in "V9 Top Pick (66.2% season HR)" and "xm_consensus_5plus". The richest context is being thrown away.

When the algorithm changes (new filters, new scoring weights), old picks become unexplainable — you see the composite_score but not how it was computed.

---

## What's Already Stored Well (Session 278 state)

Per best bet pick (`signal_best_bets_picks`):
- `signal_tags` — which signals fired
- `matched_combo_id`, `combo_classification`, `combo_hit_rate` — combo match
- `model_agreement_count`, `agreeing_model_ids` — cross-model consensus
- `consensus_bonus` — score boost from agreement
- `pick_angles` — human-readable reasoning (up to 5)
- `actual_points`, `prediction_correct` — grading outcome

---

## Three Gaps

### Gap 1: qualifying_subsets (BIGGEST WIN)

**What:** After Steps 1-2 complete (materialization), the aggregator in Step 3 should look up `current_subset_picks` to find which Level 1/2 subsets each candidate already qualified for.

**Why it matters:**
- A player in "V9 Top Pick" (66.2% season HR) AND "xm_consensus_5plus" is a MUCH stronger bet than one in zero subsets
- Subset membership is the most information-rich context we have
- It makes the "layers" actually hierarchical — Level 3 draws from Level 1+2
- Looking back at old picks, you'd see: "this player was in 4 subsets with 58-66% HR"

**What to store per pick:**
```python
qualifying_subsets = [
    {"subset_id": "top_pick", "system_id": "catboost_v9_train1102_0205"},
    {"subset_id": "nova_high_edge_all", "system_id": "catboost_v12_noveg_train1102_0205"},
    {"subset_id": "xm_consensus_5plus", "system_id": "cross_model"},
]
```

Store as `ARRAY<STRUCT<subset_id STRING, system_id STRING>>` in BQ (or JSON string for simplicity).

**Impact on scoring (optional, phase 2):** Could add a `subset_membership_bonus` to composite_score (e.g., +0.05 per qualifying subset beyond 2). But phase 1 is just observation — store and display, don't score.

### Gap 2: algorithm_version (MEDIUM WIN)

**What:** Snapshot the algorithm version per pick so we can reconstruct scoring logic later.

**Why:** If we change the scoring formula, filter thresholds, or combo weights tomorrow, old picks become hard to explain. The composite_score is stored but not HOW it was computed.

**What to store:**
```python
algorithm_version = "v279_qualifying_subsets"  # Simple version string
```

One new column: `algorithm_version STRING` in `signal_best_bets_picks`. Cheap, immensely useful for debugging.

### Gap 3: signal_regime_snapshot (NICE TO HAVE)

**What:** Store which regime (HOT/NORMAL/COLD) each signal was in when the pick was made.

**Why:** We know signals `['high_edge', 'bench_under']` fired, but not that `high_edge` was in HOT regime (1.2x weight). The regime affects scoring but isn't captured per-pick.

**What to store:**
```python
signal_regime_snapshot = {"high_edge": "HOT", "bench_under": "NORMAL"}
```

Store as JSON string in a new column. Low priority — regime is available in `signal_health_daily` by date, just not denormalized per-pick.

---

## Implementation Plan

### Part 0: Verify Session 278 deployment (5 min)

Before coding, confirm Session 278 changes are live:
```bash
# Check recent builds deployed
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5

# Check deployment drift
./bin/check-deployment-drift.sh --verbose
```

### Part 1: Qualifying Subsets Lookup (30 min)

**New file:** `ml/signals/subset_membership_lookup.py` (~60 lines)

Pure function that queries `current_subset_picks` for a given date + version_id and returns a dict mapping `player_lookup::game_id` → list of qualifying subsets.

```python
def lookup_qualifying_subsets(
    bq_client, game_date: str, version_id: str
) -> Dict[str, List[Dict]]:
    """Query which Level 1/2 subsets each player-game already appears in.

    Args:
        bq_client: BigQuery client
        game_date: Target date
        version_id: Version from SubsetMaterializer (ensures we only see
                     subsets from the current materialization batch)

    Returns:
        Dict mapping "player_lookup::game_id" to list of
        {"subset_id": str, "system_id": str, "rank_in_subset": int}
    """
    query = """
    SELECT player_lookup, game_id, subset_id, system_id, rank_in_subset
    FROM `nba_predictions.current_subset_picks`
    WHERE game_date = @game_date
      AND version_id = @version_id
      AND subset_id != 'best_bets'  -- Don't include ourselves
    ORDER BY player_lookup, game_id, subset_id
    """
    # ... group by player_lookup::game_id key
```

**Key detail:** Filter out `subset_id = 'best_bets'` to avoid circular reference. We want Level 1 + Level 2 subsets only.

### Part 2: Wire into Aggregator + Exporters (30 min)

**File: `ml/signals/aggregator.py`**
- Add `qualifying_subsets` param to `__init__` (dict from Part 1)
- In `aggregate()`, look up each candidate's qualifying subsets
- Add `qualifying_subsets` and `qualifying_subset_count` to scored pick dict
- **Phase 1:** Observation only (store, don't score)

**File: `data_processors/publishing/signal_best_bets_exporter.py`**
- After SubsetMaterializer + CrossModelSubsetMaterializer run (they already ran in the pipeline before us)
- Call `lookup_qualifying_subsets()` and pass to aggregator
- Add `qualifying_subsets` to JSON output per pick
- Add `qualifying_subsets` to BQ write

**File: `data_processors/publishing/signal_annotator.py`**
- Same pattern in `_bridge_signal_picks()` — call lookup, pass to aggregator, store

### Part 3: BQ Schema + ALTER TABLE (5 min)

**File: `schemas/bigquery/nba_predictions/signal_best_bets_picks.sql`**
```sql
qualifying_subsets STRING,     -- JSON array of {subset_id, system_id} dicts
qualifying_subset_count INT64, -- Count for easy filtering
algorithm_version STRING,      -- Algorithm version string (e.g. "v279")
```

Using STRING (JSON) for qualifying_subsets instead of ARRAY<STRUCT> because:
1. Simpler ALTER TABLE (no nested types)
2. JSON_EXTRACT functions work well for analysis
3. Array of struct requires schema migration headaches

Run ALTER TABLE on both `signal_best_bets_picks` and `current_subset_picks`.

### Part 4: Update Pick Angles (15 min)

**File: `ml/signals/pick_angle_builder.py`**
- Add new angle category (priority 2, after confidence): subset membership
- "Appears in 4 subsets: V9 Top Pick, V12 High Edge, XM 5+ Consensus, XM Diverse"
- Only fires when qualifying_subset_count >= 2

### Part 5: Algorithm Version Tagging (5 min)

Add `ALGORITHM_VERSION = "v279_qualifying_subsets"` constant in `aggregator.py`.
Pass through to BQ write. Bump whenever the scoring formula changes.

### Part 6: Update Docs + CLAUDE.md (10 min)

- Update CLAUDE.md with qualifying_subsets info
- Update START-NEXT-SESSION-HERE.md
- Mark this plan as done

### Part 7: Verify + Commit + Push (10 min)

1. Syntax check all modified Python files
2. Dry-run test of lookup + angle builder with sample data
3. Commit and push (auto-deploys)

---

## Execution Order

1. Verify Session 278 deployment
2. Create `ml/signals/subset_membership_lookup.py`
3. Wire into aggregator
4. Wire into exporter + annotator
5. BQ schema changes (ALTER TABLE)
6. Update pick angle builder
7. Add algorithm version constant
8. Update docs
9. Syntax verify all files
10. Commit + push

---

## Files Modified

| File | Change | Part |
|------|--------|------|
| `ml/signals/subset_membership_lookup.py` | NEW — subset lookup function | 1 |
| `ml/signals/aggregator.py` | Accept + pass through qualifying_subsets | 2 |
| `data_processors/publishing/signal_best_bets_exporter.py` | Call lookup, pass to aggregator, write to JSON+BQ | 2 |
| `data_processors/publishing/signal_annotator.py` | Same pattern in _bridge_signal_picks | 2 |
| `schemas/bigquery/nba_predictions/signal_best_bets_picks.sql` | Add 3 columns | 3 |
| `schemas/bigquery/predictions/06_current_subset_picks.sql` | Add qualifying_subsets column | 3 |
| `ml/signals/pick_angle_builder.py` | Add subset membership angle | 4 |
| `CLAUDE.md` | Note qualifying_subsets | 6 |
| `docs/09-handoff/START-NEXT-SESSION-HERE.md` | Update | 6 |

---

## Verification

1. **Syntax check:** `python -c "import ast; ast.parse(open(f).read())"` for all modified files
2. **BQ schema:** Run ALTER TABLE for new columns
3. **Dry run:** Import and call `lookup_qualifying_subsets()` with sample data
4. **Angle test:** Call `build_pick_angles()` with qualifying_subsets populated
5. **Deploy:** Push to main → Cloud Build auto-deploys
6. **Post-deploy query (Feb 19):**
```sql
SELECT player_name, recommendation, edge, qualifying_subsets, qualifying_subset_count, pick_angles
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = '2026-02-19'
ORDER BY rank;
```

---

## Future Work (Not This Session)

### Phase 2: Subset Membership Scoring
- Add `subset_membership_bonus` to composite_score (e.g., +0.05 per qualifying subset beyond 2)
- Requires 30+ days of observation data to validate the signal
- Backtest qualifying_subset_count vs hit rate before adding to scoring

### Phase 2b: Subset Records in Best Bets JSON
- For each qualifying subset, include its season/month/week W-L record
- Makes the output self-documenting: "This pick is in V9 Top Pick (66-45, 59.5% season)"
- Requires one additional BQ query (already computed by v_dynamic_subset_performance)

### Signal Regime Snapshot (Gap 3)
- Denormalize signal regime per-pick for full reconstruction
- Lower priority since regime is derivable from signal_health_daily by date
