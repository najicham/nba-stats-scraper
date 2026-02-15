# Session 262 Handoff — V12 Confidence Filter, Model Performance Table, Replay Engine

**Date:** 2026-02-15
**Status:** All 4 priorities completed. Code ready to commit + deploy.

---

## What Was Done

### 1. URGENT: V12 Confidence Floor (Before Feb 19)

V12 has 4 discrete confidence values (0.87, 0.90, 0.92, 0.95). The 0.87 tier has **41.7% HR on 12 picks** — well below 52.4% breakeven. The 0.90+ tier is **60.5% HR on 38 picks**.

**Fix:** Added model-specific confidence floor:
- `shared/config/model_selection.py`: `MODEL_CONFIG` with `min_confidence: 0.90` for V12
- `ml/signals/aggregator.py`: Confidence floor check after `MIN_SIGNAL_COUNT` gate
- `signal_best_bets_exporter.py` + `signal_annotator.py`: Pass `model_id` to aggregator

V9 and other models are unaffected (no confidence floor configured).

### 2. Combo Registry Cleanup

Deduplicated `signal_combo_registry` from 14 rows → 7 (INSERT had run twice).

### 3. model_performance_daily Table + Backfill

Created `nba_predictions.model_performance_daily` table:
- Rolling 7d/14d/30d HR and N per model per date
- Daily picks/wins/losses/HR/ROI
- State tracking: HEALTHY → WATCH → DEGRADING → BLOCKED
- Consecutive-day counters for threshold gates
- Action/reason tracking for state transitions
- Days since training

**Backfilled:** 47 rows from 2025-11-19 to 2026-02-12. Shows:
- V9 entered WATCH on Jan 27, BLOCKED on Jan 29 (4 days early warning)
- V12 fluctuated between WATCH and BLOCKED during Feb

### 4. Decay Detection Cloud Function

Built `orchestration/cloud_functions/decay_detection/`:
- HTTP trigger for Cloud Scheduler (11 AM ET daily)
- Reads model_performance_daily, detects state transitions
- Slack alerts to #nba-alerts with model summaries + recommendations
- Reporter pattern (always returns 200)
- Gen2 compatible (`main = decay_detection` alias)

**Not yet deployed** — needs Cloud Build trigger creation after push.

### 5. Replay Engine + CLI + Skill

Built complete replay infrastructure:
- `ml/analysis/replay_engine.py`: Core simulation engine
- `ml/analysis/replay_strategies.py`: 4 strategies (Threshold, BestOfN, Conservative, Oracle)
- `ml/analysis/replay_cli.py`: CLI with `--compare`, `--verbose`, `--output`
- `.claude/skills/replay/SKILL.md`: `/replay` Claude skill

### 6. Multi-Season Replay Results

**V9 era calibration (Nov 2025 – Feb 2026, 4 models):**

| Strategy | HR | ROI | P&L | Switches |
|----------|-----|-----|------|----------|
| **Threshold (58/55/52.4)** | **69.1%** | **31.9%** | $3,400 | 1 |
| Conservative (5d, 55%) | 67.0% | 27.8% | $3,520 | 0 |
| Oracle (hindsight) | 62.9% | 20.0% | $3,680 | 35 |
| BestOfN | 59.5% | 13.6% | $2,360 | 2 |

**Conclusion:** Standard thresholds (58/55/52.4) are well-calibrated. Threshold strategy has highest ROI because blocking bad days eliminates losses more effectively than chasing the best model.

### 7. validate-daily Phase 0.58

Added new Phase 0.58 to validate-daily skill — reads from model_performance_daily table for quick model health dashboard.

---

## Files Changed

### Modified
| File | Change |
|------|--------|
| `shared/config/model_selection.py` | Added MODEL_CONFIG, get_min_confidence() |
| `ml/signals/aggregator.py` | Added confidence floor, model_id param |
| `data_processors/publishing/signal_best_bets_exporter.py` | Pass model_id to aggregator |
| `data_processors/publishing/signal_annotator.py` | Pass model_id to aggregator |
| `.claude/skills/validate-daily/SKILL.md` | Added Phase 0.58 |

### New Files
| File | Purpose |
|------|---------|
| `ml/analysis/__init__.py` | Package marker |
| `ml/analysis/model_performance.py` | Daily metrics compute + backfill |
| `ml/analysis/replay_engine.py` | Core replay simulation |
| `ml/analysis/replay_strategies.py` | Pluggable decision strategies |
| `ml/analysis/replay_cli.py` | CLI entry point |
| `.claude/skills/replay/SKILL.md` | /replay skill |
| `orchestration/cloud_functions/decay_detection/main.py` | Decay monitor CF |
| `orchestration/cloud_functions/decay_detection/requirements.txt` | CF dependencies |
| `orchestration/cloud_functions/decay_detection/__init__.py` | Package marker |

### Infrastructure
| Change | Details |
|--------|---------|
| `model_performance_daily` BQ table | Created + backfilled 47 rows |
| `signal_combo_registry` | Deduplicated 14 → 7 rows |

---

## What Needs to Be Done Next

### Before Feb 19 (Pre-Game-Day)
- [ ] Push to main (auto-deploys Cloud Run services)
- [ ] Create Cloud Build trigger for decay-detection CF
- [ ] Create Cloud Scheduler job for decay-detection (11 AM ET daily)
- [ ] Verify V12 predictions appear for Feb 19 games
- [ ] Run validate-daily to confirm pipeline health

### Deploy Decay Detection CF
```bash
# After push to main, create the Cloud Build trigger:
gcloud builds triggers create github \
  --name="deploy-decay-detection" \
  --repository="projects/nba-props-platform/locations/us-west2/connections/nba-github-connection/repositories/nba-stats-scraper" \
  --branch-pattern="^main$" \
  --build-config="cloudbuild-functions.yaml" \
  --included-files="orchestration/cloud_functions/decay_detection/**,shared/**" \
  --service-account="projects/nba-props-platform/serviceAccounts/github-actions-deploy@nba-props-platform.iam.gserviceaccount.com" \
  --region="us-west2" \
  --project="nba-props-platform" \
  --substitutions="_FUNCTION_NAME=decay-detection,_ENTRY_POINT=decay_detection,_SOURCE_DIR=orchestration/cloud_functions/decay_detection,_TRIGGER_TYPE=http,_ALLOW_UNAUTHENTICATED=true,_MEMORY=512Mi,_TIMEOUT=300s"

# Create Cloud Scheduler job:
gcloud scheduler jobs create http decay-detection-daily \
  --location=us-west2 \
  --schedule="0 16 * * *" \
  --time-zone="UTC" \
  --uri="FUNCTION_URL" \
  --http-method=POST \
  --project=nba-props-platform
```

### Future Priorities
- [ ] Wire model_performance_daily compute into post-grading pipeline (auto-populate daily)
- [ ] Add challenger-beats-champion alert to decay_detection CF
- [ ] Test /replay skill with various scenarios
- [ ] Investigate Feb 2 crash (see `docs/09-handoff/session-prompts/SESSION-261-FEB2-INVESTIGATION.md`)

---

## Key Insights

1. **V12 confidence 0.87 tier is a clean money loser** — 41.7% HR with only 4 discrete confidence values makes filtering trivial
2. **Standard decay thresholds (58/55/52.4) are well-calibrated** — Threshold strategy had 31.9% ROI, best of all strategies
3. **Blocking bad days > picking best model** — Threshold beats Oracle because eliminating losses is more valuable than optimizing model selection
4. **V9 entered WATCH on Jan 27** — 4 days of early warning before the Feb 1-7 crash, confirming the monitoring design works retroactively
