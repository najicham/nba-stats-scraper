# Session 398 Handoff — Signal Rescue + Directional Monitoring + New Signals/Filters

**Date:** 2026-03-03 → 2026-03-04
**Status:** 3 commits deployed, signal rescue live, directional monitoring backfilled, 2 new signals + 2 new filters
**Algorithm Version:** `v398_signal_rescue`

---

## Session Summary

Session 398 implemented signal rescue — a mechanism for high-HR signals to bypass the edge floor and qualify picks that would otherwise be blocked. Also deployed directional signal monitoring (8 new columns in `signal_health_daily`, backfilled Dec 1 → Mar 2), two new signals (`denver_visitor_over`, `day_of_week_over`), two new negative filters (`friday_over_block`, `opponent_depleted_under`), and automated rescue performance monitoring via `post_grading_export`. Fixed Phase 6 correlated subquery error that blocked Mar 2-3 exports. Research sweep evaluated 6 external angles — 3 implemented, 3 dead ends.

---

## What Was Deployed

### Commit 1: `5352820e` — Directional signal monitoring + deployment fixes + new signals

| Change | Files |
|--------|-------|
| **Directional signal monitoring** | `ml/signals/signal_health.py` — 8 new columns (hr_over_7d, picks_over_7d, hr_under_7d, picks_under_7d, hr_over_30d, picks_over_30d, hr_under_30d, picks_under_30d). Backfilled Dec 1 → Mar 2. |
| **`denver_visitor_over` signal** | `ml/signals/denver_visitor_over.py` — 67.8% HR (N=118). Altitude effect for visiting players at Mile High. |
| **`day_of_week_over` signal** | `ml/signals/day_of_week_over.py` — Mon 69.9%, Thu 66.2%, Sat 67.5%. Day-of-week OVER pattern. |
| **`friday_over_block` filter** | `ml/signals/aggregator.py` — Blocks OVER on Fridays (37.5% HR best bets N=8, 53.0% raw N=443). |
| **`opponent_depleted_under` filter** | `ml/signals/aggregator.py` — Blocks UNDER when opponent has 3+ stars out (44.4% HR N=207). |
| **XGBoost/LightGBM system_id warning** | `predictions/worker/data_loaders.py` — Fixed system_id mismatch warning for non-CatBoost models. |
| **`real_signal_count` in BQ schema** | `schemas/nba_predictions/signal_best_bets_picks.sql` — New INTEGER column. |
| **`signal_health_daily` directional columns** | `schemas/nba_predictions/signal_health_daily.sql` — 8 new FLOAT/INTEGER columns. |
| **Daily-steering Step 2 enhanced** | `.claude/skills/daily-steering/SKILL.md` — Directional HR breakdown in signal health section. |
| **Signal registry** | `ml/signals/registry.py` — Registered `denver_visitor_over`, `day_of_week_over`. |
| **External research docs** | `docs/08-projects/current/external-research-angles/` — 4 research docs (Reddit, Academic, Analytics/DFS, Market Microstructure). |

### Commit 2: `ea56170e` — Signal rescue mechanism

| Change | Files |
|--------|-------|
| **Signal rescue logic** | `ml/signals/aggregator.py` — `RESCUE_TAGS` dict maps signal → direction. Picks below edge 3.0 (or OVER below 5.0) bypass floors if they have a validated rescue signal OR 2+ real (non-base) signals. |
| **`signal_rescued` + `rescue_signal` columns** | `schemas/nba_predictions/signal_best_bets_picks.sql` — BOOLEAN + STRING columns to track rescued picks. |
| **Exporter persistence** | `data_processors/publishing/signal_best_bets_exporter.py` — Writes `signal_rescued` and `rescue_signal` to BQ. |

### Commit 3: `e643b26a` — Auto-monitor rescue performance + update skills

| Change | Files |
|--------|-------|
| **Rescue performance monitoring** | `orchestration/cloud_functions/post_grading_export/main.py` — Step 4c: daily rescue HR calculation, logs WARNING if below 55% on 20+ picks. |
| **`signal_health.py` rescue monitoring** | `ml/signals/signal_health.py` — `monitor_rescue_performance()` function: per-signal HR for rescue tags over configurable window. |
| **Skills updated** | `daily-steering/SKILL.md` — Step 2.5 rescue performance section. `best-bets-config/SKILL.md` — rescue tags diagnostic. `yesterdays-grading/SKILL.md` — rescued pick grading. |

---

## Signal Rescue Architecture

### How It Works

1. After negative filters remove bad picks, the edge floor check runs
2. If a pick fails edge floor (< 3.0, or OVER < 5.0), the rescue check fires
3. **Single-signal rescue**: Pick has a signal in `RESCUE_TAGS` matching its direction → rescued
4. **Signal stacking rescue**: Pick has 2+ real (non-base) signals regardless of specific tag → rescued
5. Rescued picks get `signal_rescued=TRUE` and `rescue_signal` set to the tag (or `signal_stacking`)

### Rescue Tags (validated signals)

| Signal | Direction | HR at Edge 0-3 | Overall HR |
|--------|-----------|----------------|------------|
| `combo_3way` | OVER | N/A (backtest 95.5%) | 95.5% |
| `combo_he_ms` | OVER | N/A (backtest 94.9%) | 94.9% |
| `book_disagreement` | BOTH | 72% | 93.0% |
| `home_under` | UNDER | 75% | 63.9% |
| `low_line_over` | OVER | 66.7% | 78.1% |
| `volatile_scoring_over` | OVER | 66.7% | 81.5% |
| `high_scoring_environment_over` | OVER | 100% (edge 3-5) | 70.2% |
| `sharp_book_lean_over` | OVER | N/A | 70.3% |
| `sharp_book_lean_under` | UNDER | N/A | 84.7% |

### Both Edge Floors Bypassed

- Edge 3.0 general floor: bypassed for rescued picks
- OVER edge 5.0 floor: bypassed for rescued picks
- All other negative filters still apply (blacklist, direction affinity, quality, etc.)

### BQ Columns

- `signal_rescued` (BOOLEAN): TRUE if pick was rescued
- `rescue_signal` (STRING): Which signal/mechanism rescued it (e.g., `book_disagreement`, `signal_stacking`)
- `real_signal_count` (INTEGER): Count of non-base signals (persisted for analytics)

---

## Research Findings

### Implemented

1. **`denver_visitor_over`**: 67.8% HR (N=118) — altitude effect at Mile High for visiting players
2. **`day_of_week_over`**: Mon 69.9%, Thu 66.2%, Sat 67.5% — day-of-week OVER pattern
3. **`friday_over_block`**: 37.5% HR best bets (N=8), 53.0% raw (N=443) — worst OVER day

### Dead Ends

1. **Large spread starters UNDER**: 56.2% HR (N=283) — BELOW baseline 58.4%. Larger spreads show WORSE UNDER, not better.
2. **Timezone crossing UNDER**: 53.2% for 2+ hour tz diff — too weak for a filter.
3. **3PT mean reversion**: Already captured by `three_pt_bounce` signal. Collapsed to 16.7% in Feb (regime-dependent).

### Key Insights

- **UNDER edge is flat at 52-53% across all edge buckets** — edge is NOT a quality discriminator for UNDER. Signals are the only UNDER differentiator.
- **Signal stacking**: 2+ real signals at edge < 3 = 62.2% HR (N=45) — validates signal-based rescue
- **Premium_tags expansion not viable**: Raw edge 1-3 HR too weak for most signals to add value as premium filters

---

## Monitoring Infrastructure

### post_grading_export Steps

| Step | What | Alert |
|------|------|-------|
| 4 | `populate_signal_health_daily()` — directional splits + signal regime | On error |
| 4b | Signal canary — detects signals silent for 7+ days | Slack warning |
| 4c | `monitor_rescue_performance()` — per-rescue-tag HR | WARNING if rescue HR < 55% on 20+ picks |

### Skills Updated

| Skill | Change |
|-------|--------|
| `/daily-steering` | Step 2 directional HR breakdown, Step 2.5 rescue performance |
| `/yesterdays-grading` | Rescued pick grading callout |
| `/best-bets-config` | Rescue tags diagnostic section |
| `/hit-rate-analysis` | Query 13: rescue vs standard pick performance |
| `/top-picks` | `signal_rescued` + `rescue_signal` in pick detail |

### Slack Alerts

- Rescue underperformance: if any rescue tag < 55% HR on 20+ picks → WARNING in logs
- Dead signals: if any active signal silent for 7+ days → Slack `#nba-alerts`

---

## Known Issues / Gaps

1. **Phase 6 correlated subquery** was fixed earlier in session (commits before Session 398 scope) — blocked Mar 2-3 exports. Now resolved.
2. **Algorithm version `v398_signal_rescue`** first appears in Mar 4 picks (today's pipeline uses v397).
3. **PBP backfill deferred**: 59 dates of NBA.com PBP data in GCS not yet reprocessed to BQ. Low priority.
4. **`signal_health_daily` duplicate rows**: Multiple backfills created duplicate rows for same signal+game_date. Functional (queries use latest) but not ideal.
5. **`high_skew_over_block`**: Referenced in plan but NOT implemented — research showed 49.1% HR for high-skew OVER but needs more investigation before adding as filter. Documented in `docs/08-projects/current/external-research-angles/00-FINDINGS.md` as Tier 2 future work.

---

## Follow-Up Items for Next Session

### Priority 1: Validate Rescue Signal HR (2 weeks live)
After ~14 days of live data, check:
```sql
-- Rescue performance by signal
SELECT rescue_signal, recommendation,
  COUNT(*) as picks,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.signal_best_bets_picks bb
JOIN nba_predictions.prediction_accuracy pa USING (player_lookup, game_date, system_id)
WHERE bb.signal_rescued = TRUE
  AND bb.game_date >= '2026-03-04'
  AND pa.prediction_correct IS NOT NULL
GROUP BY 1, 2
ORDER BY hr DESC
```
If any rescue tag < 52.4% on 15+ picks, remove from `RESCUE_TAGS`.

### Priority 2: Signal-First UNDER Selection
UNDER edge is flat at 52-53% across all edge buckets — signals should drive UNDER selection, not edge. Architecture options:
- **Option A**: For UNDER picks, rank by signal quality instead of edge
- **Option B**: Lower UNDER edge floor to 1.0 and let signal density be the primary gate
- **Option C**: Create separate UNDER scoring formula: `score = signal_quality * 0.7 + edge * 0.3`

### Priority 3: Dedup `signal_health_daily` Rows
Multiple backfills created duplicates. Add `DELETE before INSERT` logic or `MERGE` statement to `populate_signal_health_daily()`.

### Priority 4: PBP Backfill (Low Priority)
59 dates of NBA.com PBP data in GCS. Deploy fix is live, just needs Pub/Sub messages to reprocess.

---

## Files Changed (All 3 Commits)

| File | Change |
|------|--------|
| `ml/signals/aggregator.py` | Signal rescue + friday_over_block + opponent_depleted_under + SC refactor |
| `ml/signals/signal_health.py` | Directional monitoring + rescue performance |
| `ml/signals/denver_visitor_over.py` | NEW signal |
| `ml/signals/day_of_week_over.py` | NEW signal |
| `ml/signals/registry.py` | Register new signals |
| `ml/signals/supplemental_data.py` | Q4 ratio query (Session 397, verified) |
| `data_processors/publishing/signal_best_bets_exporter.py` | Rescue fields persistence |
| `predictions/worker/data_loaders.py` | System ID warning fix |
| `orchestration/cloud_functions/post_grading_export/main.py` | Step 4c rescue monitoring |
| `schemas/nba_predictions/signal_best_bets_picks.sql` | 3 new columns |
| `schemas/nba_predictions/signal_health_daily.sql` | 8 new columns |
| `.claude/skills/daily-steering/SKILL.md` | Steps 2 + 2.5 |
| `.claude/skills/best-bets-config/SKILL.md` | Rescue tags section |
| `.claude/skills/yesterdays-grading/SKILL.md` | Rescued pick callout |
| `.claude/skills/hit-rate-analysis/SKILL.md` | Query 13 rescue analysis |
| `.claude/skills/top-picks/SKILL.md` | Rescue fields + presentation |
| `docs/08-projects/current/external-research-angles/*` | 5 research docs |

---

## Quick Reference Commands

```bash
# Check rescue picks in today's best bets
bq query --use_legacy_sql=false "
SELECT player_lookup, recommendation, edge, rescue_signal, signal_count
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = CURRENT_DATE() AND signal_rescued = TRUE
ORDER BY edge DESC"

# Check directional signal health
bq query --use_legacy_sql=false "
SELECT signal_name, hr_over_7d, picks_over_7d, hr_under_7d, picks_under_7d
FROM nba_predictions.signal_health_daily
WHERE game_date = (SELECT MAX(game_date) FROM nba_predictions.signal_health_daily)
ORDER BY signal_name"

# Check rescue performance since launch
bq query --use_legacy_sql=false "
SELECT bb.rescue_signal, bb.recommendation,
  COUNT(*) as n,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.signal_best_bets_picks bb
JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.signal_rescued = TRUE AND bb.game_date >= '2026-03-04'
  AND pa.prediction_correct IS NOT NULL
GROUP BY 1, 2 ORDER BY hr DESC"

# Check new filter rejections
bq query --use_legacy_sql=false "
SELECT game_date,
  JSON_VALUE(rejected_json, '$.friday_over_block') as friday_blocked,
  JSON_VALUE(rejected_json, '$.opponent_depleted_under') as opp_depleted_blocked
FROM nba_predictions.best_bets_filter_audit
WHERE game_date >= CURRENT_DATE() - 3
ORDER BY game_date DESC"
```
