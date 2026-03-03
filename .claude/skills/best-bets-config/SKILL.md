---
name: best-bets-config
description: Read-only diagnostic — single-pane-of-glass view of all best bets system thresholds, active models, signals, and sync status
---

# Skill: Best Bets Config Dashboard

Read-only diagnostic: single-pane-of-glass view of all best bets system thresholds, active models, signals, and sync status.

## Trigger
- User types `/best-bets-config`
- User asks about "best bets config", "what thresholds are active", "what models are active"

## Workflow

Run all 6 sections below and present results as a formatted dashboard.

---

### Section 1: Aggregator Config

Read constants from `ml/signals/aggregator.py`:

```bash
grep -E 'MIN_EDGE|MIN_SIGNAL_COUNT|ALGORITHM_VERSION|HIGH_EDGE_SC_THRESHOLD' ml/signals/aggregator.py
```

Also show the current best bets model:
```bash
gcloud run services describe prediction-coordinator --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env)" 2>/dev/null \
  | tr ',' '\n' | grep BEST_BETS
```

Display as:
```
## 1. Aggregator Config
| Setting                  | Value                    |
|--------------------------|--------------------------|
| ALGORITHM_VERSION        | (from grep)              |
| MIN_EDGE                 | 3.0                      |
| MIN_SIGNAL_COUNT         | 3 (edge 7+)             |
| MIN_SIGNAL_COUNT_LOW_EDGE| 4 (edge < 7)            |
| HIGH_EDGE_SC_THRESHOLD   | 7.0                      |
| Best Bets Model          | (from env var)           |
```

---

### Section 2: Active Model Families

Query BQ for enabled models from the registry:

```sql
SELECT model_id, model_family, status, enabled,
  training_start_date, training_end_date,
  DATE_DIFF(CURRENT_DATE(), training_end_date, DAY) as days_stale
FROM nba_predictions.model_registry
WHERE enabled = TRUE
ORDER BY days_stale ASC
```

Also check active predictions:
```sql
SELECT DISTINCT system_id
FROM nba_predictions.player_prop_predictions
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  AND is_active = TRUE
ORDER BY system_id
```

Flag:
- Enabled models with no recent predictions → **NO PREDICTIONS**
- Models with `days_stale > 14` → **STALE**
- Models with `days_stale > 21` → **OVERDUE RETRAIN**

---

### Section 3: Negative Filter Inventory

Display the full set of negative filters from `ml/signals/aggregator.py`:

```
## 3. Negative Filters (27 filters)
| #  | Filter                      | Condition                                     | Session |
|----|-----------------------------|-----------------------------------------------|---------|
| 1  | legacy_block                | Model in LEGACY_MODEL_BLOCKLIST               | 332     |
| 2  | blacklist                   | Player <40% HR on 8+ edge-3+ picks            | 284     |
| 3  | edge_floor                  | edge < 3.0                                    | 352     |
| 4  | over_edge_floor             | OVER + edge < 5.0 (v9 only)                   | 297     |
| 5  | under_edge_7plus            | UNDER + edge >= 7 (v9 only)                   | 297,318 |
| 6  | model_direction_affinity    | Model+dir+edge combo HR < 45% on 15+ picks    | 343     |
| 7  | away_noveg                  | v12_noveg/v9 family + AWAY game                | 365     |
| 8  | familiar_matchup            | 6+ games vs same opponent                      | 284     |
| 9  | quality_floor               | Feature quality < 85                            | 278     |
| 10 | bench_under                 | UNDER + line < 12                               | 278     |
| 11 | star_under                  | Star UNDER (line >= 23) injury-aware            | 297,367 |
| 12 | under_star_away             | UNDER + Star + AWAY (line >= 23)                | 371     |
| 13 | med_usage_under             | Medium teammate usage + UNDER                   | 371     |
| 14 | starter_v12_under           | Starter V12 UNDER (line 15-20)                  | 371     |
| 15 | line_jumped_under           | UNDER + prop_line_delta >= 2.0                  | 306     |
| 16 | line_dropped_under          | UNDER + prop_line_delta <= -2.0                 | 306     |
| 17 | line_dropped_over           | OVER + prop_line_delta <= -2.0                  | 374b    |
| 18 | neg_pm_streak               | UNDER + 3+ negative +/- games                   | 294     |
| 19 | opponent_under_block        | UNDER + opponent in {MIN, MEM, MIL}             | 372     |
| 20 | opponent_depleted_under     | UNDER + 3+ opponent stars out                    | 374b    |
| 21 | high_book_std_under         | UNDER + high multi-book line std                 | 374     |
| 22 | model_profile_would_block   | Per-model slice HR observation (not enforced)    | 384     |
| 23 | signal_count                | SC < 4 (edge < 7) or SC < 3 (edge 7+)           | 370,388 |
| 24 | starter_over_sc_floor       | Starter OVER (line 15-25) with SC < 5            | 382c    |
| 25 | confidence                  | Confidence below MIN_CONFIDENCE                  | -       |
| 26 | anti_pattern                | Anti-pattern combo detected                      | -       |
| 27 | signal_density              | Base-only signals + edge < 7                     | 352     |
```

---

### Section 4: Signal Registry & Health

Query signal health:
```sql
SELECT signal_tag, regime, hit_rate_7d, sample_size_7d, timeframe
FROM nba_predictions.signal_health_daily
WHERE game_date = (SELECT MAX(game_date) FROM nba_predictions.signal_health_daily)
ORDER BY signal_tag, timeframe
```

Cross-reference with registered signals:
```bash
grep -E "tag=" ml/signals/registry.py | grep -v '#'
```

Display as:
```
## 4. Signal Registry & Health
| Signal            | Registered | Regime  | HR 7d  | N 7d | Status      |
|-------------------|------------|---------|--------|------|-------------|
| high_edge         | Yes        | HOT     | 66.7%  | 20   | PRODUCTION  |
| ...               | ...        | ...     | ...    | ...  | ...         |
```

Include graduation progress for combo signals (combo_he_ms, combo_3way) — show N toward the 50-sample gate.

---

### Section 5: Combo Registry

Query combo registry:
```sql
SELECT combo_id, signal_tags, classification, overall_hit_rate, total_samples, status
FROM nba_predictions.signal_combo_registry
ORDER BY classification, combo_id
```

Display as:
```
## 5. Combo Registry
| Combo ID           | Signals           | Classification | HR     | N   | Status |
|--------------------|-------------------|----------------|--------|-----|--------|
| combo_he_ms        | high_edge+min_sur | SYNERGISTIC    | 94.9%  | 39  | ACTIVE |
| ...                | ...               | ...            | ...    | ... | ...    |
```

---

### Section 6: Config Sync & Process Health

Run these automated checks:

| Check | How | Alert If |
|-------|-----|----------|
| All BQ system_ids classified | Query BQ → classify_system_id patterns | Unclassified found |
| signal_health_daily fresh | `SELECT MAX(game_date)` | > 2 days stale |
| combo_registry populated | `SELECT COUNT(*)` | Empty |
| Models have grading data | prediction_accuracy by system_id last 7d | 0 graded |
| Signals firing in production | pick_signal_tags last 7d | PRODUCTION signal silent 3+ days |

```sql
-- Freshness check
SELECT
  'signal_health_daily' as table_name,
  MAX(game_date) as latest_date,
  DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY) as days_stale
FROM nba_predictions.signal_health_daily;

-- Grading coverage by model (enabled models only)
SELECT pa.system_id, COUNT(*) as graded_last_7d
FROM nba_predictions.prediction_accuracy pa
JOIN nba_predictions.model_registry mr ON pa.system_id = mr.model_id
WHERE pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND mr.enabled = TRUE
GROUP BY 1
ORDER BY 1;

-- Signal firing check
SELECT signal_tag, COUNT(DISTINCT game_date) as days_fired_7d
FROM nba_predictions.pick_signal_tags,
  UNNEST(signal_tags) as signal_tag
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1
ORDER BY 1;
```

Display sync status with pass/fail indicators.

---

### Checklists (always show at bottom)

```
## New Model Checklist
- [ ] Pattern in MODEL_FAMILIES (shared/config/cross_model_subsets.py)
- [ ] Subset definitions in BQ dynamic_subset_definitions
- [ ] Entry in model_codenames.py / subset_public_names.py
- [ ] Grading pipeline producing prediction_accuracy rows
- [ ] Auto-discovered by discover_models() (verified by Section 2 above)

## New Signal Checklist
- [ ] Signal class in ml/signals/
- [ ] Registered in registry.py
- [ ] Documented in CLAUDE.md signal table
- [ ] Appearing in signal_health_daily
- [ ] Firing in pick_signal_tags (or justification for silence)
- [ ] Combo participation evaluated
```
