# Session 150 Prompt

Read the Session 149 handoff for full context: `docs/09-handoff/2026-02-07-SESSION-149-HANDOFF.md`

## Context

Session 149 completed both tasks from Session 148's prompt:
1. **BDL query migration** — All 8 active `bdl_player_boxscores` queries replaced with `nbac_gamebook_player_stats`. DNP detection updated for nbac minutes format.
2. **Cloud Build optimization** — Lock files for raw + scrapers, Dockerfile reordering for layer caching, error suppression fix, conditional GCS model download.
3. **BDL issue tracking** — New `nba_orchestration.bdl_service_issues` view + `bin/monitoring/bdl_issue_report.py` report script.

All 6 services deployed at commit `5a123df1`. Pipeline healthy.

## BDL Status

**32/33 days full outage, 2.4% data delivery rate.** BDL is effectively dead. Generate a cancellation report:
```bash
PYTHONPATH=. python bin/monitoring/bdl_issue_report.py --output bdl_cancellation_report.md
```

## Suggested Priorities

### 1. Breakout Classifier V3 (HIGH)
Session 135 roadmap identifies 4 high-impact contextual features:
- `star_teammate_out` — Star teammates OUT (+0.04-0.07 AUC expected)
- `fg_pct_last_game` — Hot shooting rhythm
- `points_last_4q` — 4Q performance signal
- `opponent_key_injuries` — Weakened defense

Infrastructure is ready: injury integration at `predictions/shared/injury_integration.py`, shared feature module at `ml/features/breakout_features.py`.

See: `docs/09-handoff/2026-02-05-SESSION-135-BREAKOUT-V2-AND-V3-PLAN.md`

### 2. Feature Completeness (MEDIUM)
Coverage is ~75 predictions/game due to zero tolerance defaults. To increase without relaxing tolerance:
- Check which features are most commonly defaulted: `SELECT idx, COUNT(*) FROM nba_predictions.ml_feature_store_v2, UNNEST(default_feature_indices) as idx WHERE game_date >= CURRENT_DATE() - 7 GROUP BY 1 ORDER BY 2 DESC`
- Fix upstream data gaps in Phase 4 processors

See: `docs/08-projects/current/feature-completeness/00-PROJECT-OVERVIEW.md`

### 3. BDL Formal Decommission (LOW)
When ready, clean up the ~10 config files that still reference BDL as a fallback source. See the "Remaining BDL References" section in the Session 149 handoff.

## Verification
```bash
# Run daily validation
/validate-daily

# Check deployment drift
./bin/check-deployment-drift.sh --verbose

# Check BDL status
bq query --use_legacy_sql=false "SELECT * FROM nba_orchestration.bdl_service_issues ORDER BY game_date DESC LIMIT 10"
```
