# Session 151 Handoff - Breakout V3 + Feature Completeness + BDL Decommission

**Date:** 2026-02-07
**Commit:** (pending push)

## Changes Summary

### 1. Breakout V3 Model — Trained & Evaluated

Ran V3 breakout training with 13 features (2 new: `star_teammate_out`, `fg_pct_last_game`).

**Results (7-day eval, N=520):**

| Metric | V2 Baseline | V3 Result |
|--------|-------------|-----------|
| AUC-ROC | 0.5708 | **0.5924 (+0.0216)** |
| Training AUC | 0.5708 | 0.6714 |
| High-confidence (>=0.769) | 0 | 0 |

**Feature Importance:**
1. `minutes_increase_pct` (13.3%) — jumped to #1
2. `points_avg_season` (11.5%)
3. `fg_pct_last_game` (11.4%) — V3 new, strong contributor
4. `pts_vs_season_zscore` (8.8%)
5. `days_since_breakout` (8.7%)
6. `explosion_ratio` (7.4%)
7. `opponent_def_rating` (7.3%)
8. `back_to_back` (7.3%)
9. `points_std_last_10` (6.9%)
10. `points_avg_last_5` (5.5%)
11. `home_away` (5.1%)
12. `star_teammate_out` (3.8%) — V3 new, meaningful variance
13. `minutes_avg_last_10` (2.9%)

**Distribution shift concern:** `star_teammate_out` mean is 0.971 in eval vs 0.213 in training (4.5x). Feb 1-7 had unusually many star absences. The feature has variance (std=0.669) but the shift may suppress AUC.

**No model promoted to production.** V3 shows modest improvement but still no high-confidence predictions. Keep V2 in shadow mode.

### 2. Feature Completeness — Fallback Gaps Fixed

**File:** `data_processors/precompute/ml_feature_store/feature_extractor.py`

- Added `mid_range_rate_last_10` to `_compute_cache_fields_from_games()` (was computing paint/three-point rates but missing mid-range)
- Added `team_pace_last_10` and `team_off_rating_last_10` to fallback computation using `_team_games_lookup` data
- Expanded `_batch_extract_team_games()` to fetch `pace` and `offensive_rating` fields (was only fetching `win_flag`)

**Expected impact:** Unblocks ~48 players/day who fail quality gate due to missing team context features (indices 22-23) and mid-range rate (index 19).

### 3. BDL Formal Decommission — Config Cleanup

Removed dead BDL service references from 10 config files. BDL has been in full outage 32+ days with 2.4% data delivery rate.

| File | Change |
|------|--------|
| `shared/config/orchestration_config.py` | Removed `p2_bdl_box_scores` from expected/required processor lists |
| `config/workflows.yaml` | Removed `bdl_standings`, `bdl_active_players`, `bdl_box_scores` scraper definitions + all workflow references |
| `config/workflows.yaml` | Removed 3 BDL catchup workflows (midday, afternoon, evening) |
| `shared/config/service_urls.py` | Removed `BALLDONTLIE` and `BALLDONTLIE_LIVE` from ExternalAPIs |
| `.env.example` | Removed `BDL_API_KEY` |
| `docker-compose.dev.yml` | Removed `BDL_API_KEY` env var |
| `bin/scrapers/deploy/deploy_scrapers_simple.sh` | Removed `BDL_API_KEY` from --set-secrets |
| `bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh` | Removed `BDL_API_KEY` conditional |
| `shared/utils/secrets.py` | Removed `get_bdl_api_key()` method |
| `scrapers/registry.py` | Removed 6 non-injury BDL scraper entries (kept `bdl_injuries`) |

**Kept intact:** BDL injury scraper, actual scraper source code (`scrapers/balldontlie/`), tests, backfill scripts, monitoring tools, MLB BDL scrapers.

## Verification

```bash
# Validate Python configs
python -c "from shared.config.orchestration_config import get_orchestration_config; print('OK')"
python -c "from scrapers.registry import SCRAPER_REGISTRY; print('bdl_injuries' in SCRAPER_REGISTRY)"

# Check no BDL in critical configs
grep -r 'bdl_box_scores\|BDL_API_KEY\|BALLDONTLIE' config/ shared/config/ shared/utils/secrets.py

# Validate workflows YAML
python -c "import yaml; yaml.safe_load(open('config/workflows.yaml')); print('OK')"
```

## Deployment

Feature completeness fix affects `nba-phase4-precompute-processors` service. Auto-deploy triggers on push to main.

## Next Session Priorities

1. **Monitor feature completeness impact** — After deploy, check if default_feature_count drops for team context features:
   ```sql
   SELECT game_date, COUNTIF(default_feature_count = 0) as clean, COUNT(*) as total
   FROM nba_predictions.ml_feature_store_v2
   WHERE game_date >= '2026-02-08'
   GROUP BY 1
   ```

2. **Breakout V3 larger evaluation** — Try 2-week or month-long eval window. Current 7-day eval shows +0.02 AUC but the `star_teammate_out` distribution shift (4.5x) needs investigation.

3. **Remaining BDL cleanup** — Session 149 identified additional config files that still reference BDL as fallback:
   - `shared/config/scraper_retry_config.yaml`
   - `shared/config/data_sources/fallback_config.yaml`
   - `shared/validation/config.py`
   - `shared/validation/chain_config.py`
   - `shared/processors/patterns/smart_skip_mixin.py`
   - `shared/processors/patterns/fallback_source_mixin.py`
   - `shared/processors/patterns/quality_columns.py`
   - `shared/validation/phase_boundary_validator.py`
   - `shared/validation/validators/phase1_validator.py`
   - `shared/validation/validators/phase2_validator.py`
