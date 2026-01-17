# MLB vs NBA Feature Gap Analysis

**Created**: 2026-01-16
**Analysis Date**: 2026-01-16

## Executive Summary

MLB infrastructure is significantly behind NBA in supporting systems. While the core prediction pipeline works (scrapers → analytics → precompute → predictions → grading), the operational infrastructure is minimal.

---

## 1. Publishing/Exporters

### NBA Has (22 Exporters)

Located in `data_processors/publishing/`:

| Exporter | Purpose | MLB Equivalent Needed |
|----------|---------|----------------------|
| `predictions_exporter.py` | Daily predictions → GCS | **YES** - Core functionality |
| `best_bets_exporter.py` | High-confidence plays | **YES** - Key user feature |
| `live_grading_exporter.py` | Real-time accuracy | **YES** - Model monitoring |
| `system_performance_exporter.py` | Model performance | **YES** - V1.4 vs V1.6 tracking |
| `tonight_player_exporter.py` | Today's player focus | **YES** - Daily pitcher cards |
| `tonight_all_players_exporter.py` | All today's players | YES - All pitchers |
| `streaks_exporter.py` | Hot/cold streaks | NICE TO HAVE |
| `bounce_back_exporter.py` | Regression analysis | NICE TO HAVE |
| `player_profile_exporter.py` | Player profiles | YES - Pitcher profiles |
| `player_season_exporter.py` | Season summaries | YES - Season stats |
| `player_game_report_exporter.py` | Game-by-game reports | NICE TO HAVE |
| `results_exporter.py` | Game results | **YES** - Track outcomes |
| `live_scores_exporter.py` | Real-time scores | NICE TO HAVE |
| `status_exporter.py` | System status | YES - Pipeline health |
| `news_exporter.py` | News/updates | NO - Not applicable |
| `team_tendencies_exporter.py` | Team patterns | NICE TO HAVE |
| `quick_hits_exporter.py` | Quick analysis | NICE TO HAVE |
| `what_matters_exporter.py` | Key metrics | NICE TO HAVE |
| `whos_hot_cold_exporter.py` | Current form | NICE TO HAVE |
| `tonight_trend_plays_exporter.py` | Trend plays | NICE TO HAVE |
| `deep_dive_exporter.py` | Detailed analysis | NICE TO HAVE |
| `base_exporter.py` | Base class | **YES** - Foundation |

### MLB Has

**NONE** - No exporters exist.

### Minimum Viable Set for MLB (7 Exporters)

```
data_processors/publishing/mlb/
├── __init__.py
├── mlb_base_exporter.py              # Base class (extend NBA's)
├── mlb_predictions_exporter.py       # Daily predictions → GCS
├── mlb_best_bets_exporter.py         # High-edge picks
├── mlb_system_performance_exporter.py # V1.4 vs V1.6 accuracy
├── mlb_pitcher_profile_exporter.py   # Pitcher detail pages
├── mlb_results_exporter.py           # Game outcomes
└── mlb_status_exporter.py            # Pipeline health status
```

---

## 2. Monitoring Systems

### NBA Has (15+ Modules)

Located in `monitoring/`:

| Module | Purpose | MLB Equivalent Needed |
|--------|---------|----------------------|
| `processors/gap_detection/` | Detect GCS files not in BigQuery | **YES** - Critical |
| `processors/execution/` | Track stuck processors | **YES** - Critical |
| `scrapers/freshness/` | Data freshness checks | **YES** - Critical |
| `stall_detection/` | Pipeline stall detection | **YES** - Critical |
| `pipeline_latency_tracker.py` | E2E latency measurement | YES - Performance |
| `processor_slowdown_detector.py` | Slowdown alerts | YES - Performance |
| `firestore_health_check.py` | Orchestration state | YES - If using Firestore |
| `resolution_health_check.py` | Data resolution quality | NICE TO HAVE |
| `health_summary/` | Daily health reports | YES - Operational |
| `scripts/workflow_monitoring.py` | Workflow status | NICE TO HAVE |
| `scripts/check-scrapers.py` | Scraper health | YES - Data ingestion |

### MLB Has

**1 script only**: `bin/monitoring/mlb_daily_health_check.sh`

This script checks:
- Service health endpoints (5 Cloud Run services)
- Games scheduled (season detection)
- Raw data availability
- Analytics completeness
- Precompute features
- Predictions volume
- Grading accuracy
- Recent errors
- Scheduler job status
- Pub/Sub queue depth

**Missing:**
- Automated gap detection (files → BigQuery)
- Continuous freshness monitoring
- Stall detection
- Latency tracking
- Execution monitoring (stuck processors)

### Minimum Viable Set for MLB (5 Modules)

```
monitoring/mlb/
├── __init__.py
├── mlb_gap_detection.py              # GCS → BigQuery gaps
├── mlb_freshness_checker.py          # Data freshness monitoring
├── mlb_prediction_coverage.py        # Ensure all pitchers covered
├── mlb_execution_monitor.py          # Track stuck processors
└── mlb_stall_detector.py             # Pipeline stall alerts
```

---

## 3. Validation Framework

### NBA Has (7+ Validators)

Located in `validation/`:

| Validator | Purpose | MLB Equivalent Needed |
|-----------|---------|----------------------|
| `base_validator.py` | Universal validation framework | **Already shared** |
| `validators/predictions/prediction_coverage_validator.py` | Ensure all players predicted | **YES** - Critical |
| `validators/raw/odds_api_props_validator.py` | Validate betting lines | **YES** - Data quality |
| `validators/raw/bdl_boxscores_validator.py` | Validate game stats | **YES** - Data quality |
| `validators/raw/nbac_schedule_validator.py` | Validate schedule data | **YES** - Data quality |
| `validators/raw/espn_scoreboard_validator.py` | Validate scoreboard | NICE TO HAVE |
| `validators/raw/odds_game_lines_validator.py` | Validate game lines | NICE TO HAVE |
| `validators/raw/nbac_gamebook_validator.py` | Validate gamebooks | NO - Not applicable |

### MLB Has

**0 production validators** - Only ad-hoc training scripts:
- `scripts/mlb/baseline_validation.py` - Training validation
- `scripts/mlb/historical_odds_backfill/validate_player_matching.py` - One-time
- `scripts/mlb/training/walk_forward_validation.py` - Model validation

### Minimum Viable Set for MLB (5 Validators)

```
validation/validators/mlb/
├── __init__.py
├── mlb_schedule_validator.py         # Validate schedule + pitchers
├── mlb_pitcher_props_validator.py    # Validate betting lines loaded
├── mlb_pitcher_stats_validator.py    # Validate game stats
├── mlb_prediction_coverage_validator.py  # Ensure all pitchers predicted
└── mlb_analytics_validator.py        # Validate rolling stats computed
```

Each needs a YAML config in `validation/configs/mlb/`.

---

## 4. Alert Manager Integration

### NBA Has

Full integration with `shared/alerts/AlertManager`:
- Rate limiting (prevent spam during backfill)
- Backfill mode (suppress non-critical alerts)
- Alert batching (combine similar alerts)
- Multi-channel (email, Slack, Sentry)
- Severity-based routing

### MLB Has

**Unknown** - Need to verify if MLB services use AlertManager.

### Required Integration Points

MLB services that should use AlertManager:
1. `main_mlb_analytics_service.py` - Analytics failures
2. `main_mlb_precompute_service.py` - Precompute failures
3. `predictions/mlb/worker.py` - Prediction failures
4. `main_mlb_grading_service.py` - Grading failures
5. Monitoring scripts - When issues detected

---

## 5. Other Gaps

### MLB-Specific Features NBA Doesn't Need

These are documented in `mlb-pitcher-strikeouts/ULTRATHINK-MLB-SPECIFIC-ARCHITECTURE.md`:

| Feature | Status | Notes |
|---------|--------|-------|
| Lineup-level analysis (bottom-up K) | Partially implemented | f25-f28 features exist |
| Pitcher arsenal analysis | Not implemented | Pitch mix, velocity trends |
| Batter K vulnerability profiles | Not implemented | Platoon splits |
| Umpire strike zone analysis | Not implemented | K rate adjustments |
| Innings projection | Not implemented | IP variance handling |

---

## Implementation Priority

### Phase 1: Monitoring (CRITICAL)
**Estimated Effort**: 2-3 days
- Without monitoring, can't detect issues
- Must have before production season

### Phase 2: Validation (HIGH)
**Estimated Effort**: 2-3 days
- Catches data quality issues early
- Prevents bad predictions

### Phase 3: Publishing (HIGH)
**Estimated Effort**: 3-4 days
- Makes predictions useful
- Enables API/website features

### Phase 4: Alert Integration (MEDIUM)
**Estimated Effort**: 1 day
- Prevents alert spam
- Proper routing

---

## Total Estimated Effort

| Phase | Days | Deliverables |
|-------|------|--------------|
| Monitoring | 2-3 | 5 monitoring modules |
| Validation | 2-3 | 5 validators + configs |
| Publishing | 3-4 | 7 exporters |
| Alerting | 1 | Integration verification |
| **Total** | **8-11** | Full feature parity |
