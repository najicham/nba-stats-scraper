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
grep -E 'MIN_EDGE|MIN_SIGNAL_COUNT|ALGORITHM_VERSION' ml/signals/aggregator.py
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
| Setting              | Value              |
|----------------------|--------------------|
| ALGORITHM_VERSION    | v307_multi_source  |
| MIN_EDGE             | 5.0                |
| MIN_SIGNAL_COUNT     | 2                  |
| Best Bets Model      | (from env var)     |
```

---

### Section 2: Active Model Families

Query BQ for distinct system_ids in last 3 days:

```sql
SELECT DISTINCT system_id
FROM nba_predictions.player_prop_predictions
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  AND is_active = TRUE
  AND (system_id LIKE 'catboost_%')
ORDER BY system_id
```

Cross-reference against `MODEL_FAMILIES` in `shared/config/cross_model_subsets.py` by calling `classify_system_id()` mentally or via grep. Flag:
- Any system_id that does NOT match a known family pattern → **UNCLASSIFIED**
- Any family in MODEL_FAMILIES with no active predictions → **INACTIVE**

Display as:
```
## 2. Active Model Families
| system_id                              | Family   | Status |
|----------------------------------------|----------|--------|
| catboost_v9                            | v9_mae   | ACTIVE |
| catboost_v12_noveg_train...            | v12_mae  | ACTIVE |
| ...                                    | ...      | ...    |
```

---

### Section 3: Negative Filter Inventory

Display the full set of negative filters from the aggregator. Read from `ml/signals/aggregator.py` docstring + code:

```
## 3. Negative Filters
| # | Filter                   | Threshold        | HR     | Session | Code Location          |
|---|--------------------------|------------------|--------|---------|------------------------|
| 1 | Player blacklist         | <40% HR, 8+ picks| varies | 284     | aggregator.py L114     |
| 2 | Edge floor               | edge < 5.0       | 57%    | 297     | aggregator.py L120     |
| 3 | UNDER edge 7+ block      | UNDER + edge>=7  | 40.7%  | 297,318 | aggregator.py L125     |
| 4 | Avoid familiar           | 6+ games vs opp  | varies | 284     | aggregator.py L130     |
| 5 | Feature quality floor    | quality < 85     | 24.0%  | 278     | aggregator.py L135     |
| 6 | Bench UNDER block        | UNDER + line<12  | 35.1%  | 278     | aggregator.py L140     |
| 7 | Line jumped UNDER block  | UNDER + delta>=2 | 38.2%  | 306     | aggregator.py L146     |
| 8 | Line dropped UNDER block | UNDER + delta<=-2| 35.2%  | 306     | aggregator.py L152     |
| 9 | Neg +/- streak UNDER     | UNDER + 3+ neg   | 13.1%  | 294     | aggregator.py L158     |
|10 | MIN_SIGNAL_COUNT         | < 2 signals      | n/a    | 259     | aggregator.py L170     |
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
| model_health      | Yes        | NORMAL  | 52.6%  | 100  | PRODUCTION  |
| high_edge         | Yes        | HOT     | 66.7%  | 20   | BLOCKED     |
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

-- Grading coverage by model
SELECT system_id, COUNT(*) as graded_last_7d
FROM nba_predictions.prediction_accuracy
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND system_id LIKE 'catboost_%'
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
