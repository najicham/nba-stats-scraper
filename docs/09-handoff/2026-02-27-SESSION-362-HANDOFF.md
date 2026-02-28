# Session 362 Handoff — Daily Validation (Feb 27, 2026 9:39 PM ET)

## Session Type
Daily validation — pre-game check for tonight's 5-game slate.

## Pipeline Status: OPERATIONAL (Models Degraded)

The data pipeline is fully functional — scrapers, Phase 3 analytics, Phase 4 features, Phase 5 predictions, and Phase 6 exports are all working. The systemic issue is **model performance**, not infrastructure.

---

## Critical Findings

### 1. ALL Models Below Breakeven (P1)

Every model in the fleet is in `BLOCKED` state in `model_performance_daily`:

| Model | 7d HR | 7d N | 14d HR | 14d N | Days Since Training |
|-------|-------|------|--------|-------|---------------------|
| v9_low_vegas_train0106_0205 | 51.9% | 52 | 54.2% | 59 | 17 |
| v12_q43_train1225_0205 | 50.0% | 20 | 50.0% | 20 | 11 |
| v9_q45_train1102_0125 | 50.0% | 30 | 48.5% | 33 | 32 |
| **catboost_v12 (champion)** | **45.8%** | **83** | **48.9%** | **94** | **11** |

Champion V12 edge 3+ rolling HR: **50.0% (7d, N=68)** / **51.1% (14d, N=90)** — both below the 52.4% breakeven threshold.

**Key context**: This aligns with the February decline diagnosis from Session 348 (OVER predictions collapsed, full-vegas architecture failing). The shadow fleet rebuild (Sessions 350-361) is the correct strategic response — new models need time to accumulate graded picks.

**Models to watch**:
- `catboost_v16_noveg_train1201_0215` (Session 357): 70.8% backtest HR edge 3+. First live predictions expected around Feb 28. Needs 2-3 days of graded data.
- `lgbm_v12_noveg_train1102_0209` / `lgbm_v12_noveg_train1201_0209` (Session 350): 67-73% backtest HR. Accumulating data.
- `catboost_v12_train1201_0215` (Session 359, vegas=0.25): **75.0% backtest HR edge 3+**. Accumulating data.
- `catboost_v16_noveg_rec14_train1201_0215` (Session 359): 69.0% backtest HR. Best UNDER model candidate.

**Action**: No immediate action — wait for shadow models to accumulate graded picks (target: 50+ edge 3+ graded). Check back in 2-3 days. Do NOT promote any model until it has sufficient live sample size.

### 2. Heavy UNDER Directional Skew Tonight (P2 WARNING)

V12 edge 3+ picks for Feb 27: **88.9% UNDER** (8/9 picks). Near the 90% critical threshold.

Historical context: When >90% of picks are in one direction, hit rates drop significantly. At 88.9%, this is borderline.

**Action**: Exercise caution with tonight's bets. Consider reduced sizing.

### 3. Firestore Phase 3 Trigger Tracking Degraded (P3)

Firestore completion records are inconsistent:
- Feb 26: 3/5 processors tracked, `_triggered=False`
- Feb 27: 1/5 processors tracked (only `upcoming_player_game_context`), `_triggered=False`

Despite this, **data is flowing correctly** — analytics exist for Feb 26 (10 games, 369 records), predictions exist for Feb 27 (66 per model). Backup Cloud Scheduler jobs are compensating for the orchestrator trigger not firing.

**Possible causes**:
- Orchestrator Firestore write failures (permissions or quota)
- Phase 3 processors completing but not reporting to Firestore
- The `_mode` field is `unknown` for both dates, suggesting the mode-aware orchestration may not be setting it

**Action**: Investigate orchestrator logs when convenient. Not urgent since backup schedulers are working.

---

## Infrastructure Health Summary

### Passing Checks

| Check | Result |
|-------|--------|
| Live-export env vars | BDL_API_KEY + GCP_PROJECT present |
| Pub/Sub IAM | All 18 services have correct IAM |
| Scheduler health | 112/113 passing |
| Phase 3 analytics | Feb 26: 10/10 games complete |
| Phase 5 predictions | Feb 27: 66 per model, all with prop lines |
| Phase 6 exports | Best bets + picks JSON published at ~5 PM ET |
| Cross-model parity | All 11 models have 65-66 predictions |
| Grading completeness | Core models 83-94% coverage (7-day) |

### Minor Issues

| Issue | Severity | Detail |
|-------|----------|--------|
| Deployment drift | P3 | 8 services behind HEAD from V17 experiment commit (`a559702f`). V17 is a confirmed dead end — no urgency |
| `self-heal-predictions` scheduler | P4 | DEADLINE_EXCEEDED (code 4). Needs timeout increase |
| New model grading | INFO | train1225_0209 batch at 8.3% coverage, q55_tw_train0105_0215 at 0% — expected for newly deployed models |
| Feature store (Feb 28) | INFO | 0% quality_ready, 100% cache miss — expected, Phase 4 hasn't run for tomorrow yet |

### Validation Note: game_id Format Mismatch

The Phase 0.35 game-level coverage check (comparing `nba_reference.nba_schedule` vs `nba_analytics.player_game_summary`) reported a **false alarm** of 0/10 games covered for Feb 26. Root cause: game_id formats differ between tables:
- Schedule: `0022500852` (NBA numeric ID)
- Analytics: `20260226_MIA_PHI` (date_away_home format)

The JOIN on `game_id` fails silently. **The data is actually complete** (verified by counting games independently). Future sessions should fix the coverage check query to join on `game_date` + team instead, or normalize game_id formats.

---

## Deployment Status

Deployed at HEAD (`bd7f451`):
- phase3-to-phase4-orchestrator, phase4-to-phase5-orchestrator, phase5-to-phase6-orchestrator
- grading-gap-detector, phase5b-grading, validate-freshness
- nba-phase1-scrapers, reconcile

Behind HEAD (`a559702f` — V17 experiment, dead end):
- nba-phase3-analytics-processors, nba-phase4-precompute-processors
- prediction-coordinator, prediction-worker
- nba-grading-service, daily-health-check, validation-runner, pipeline-health-summary

**No deployment needed** — the only undeployed changes are V17 opportunity risk features which are a confirmed dead end (Session 360: all features < 1% importance, 56.7% HR).

---

## Recommended Next Steps

1. **Monitor shadow fleet daily** — Check grading coverage and HR for V16, LightGBM, and vegas=0.25 models over the next 2-3 days
2. **Fix Phase 0.35 coverage query** — Join on `game_date` + team tricode instead of `game_id` to avoid false alarms
3. **Investigate Firestore trigger tracking** — Check why `_triggered` is False and `_mode` is unknown despite data flowing
4. **Increase `self-heal-predictions` timeout** — Currently hitting DEADLINE_EXCEEDED
5. **Do NOT deploy V17 code** — It's a dead end. The 8 stale services are fine as-is
6. **Model promotion decision**: When any shadow model reaches 50+ graded edge 3+ picks with HR >= 60%, it's a candidate for promotion. Run `/model-experiment` backtest to validate before promoting.
