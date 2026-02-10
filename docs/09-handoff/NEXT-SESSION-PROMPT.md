Read docs/09-handoff/2026-02-09-SESSION-179B-HANDOFF.md and work through priorities:

- P0: **Run the experiment sweep.** Session 179B built 16 new flags into `quick_retrain.py` for breaking Vegas dependency. All code is tested (dry-run verified). Start with the A1 Vegas Weight Sweep (6 experiments) to find the sweet spot — commands are in the handoff's P0 section and in `.claude/skills/model-experiment/SKILL.md` under "Master Experiment Plan". Use `--train-start 2025-11-02 --train-end 2026-01-31 --eval-start 2026-02-01 --eval-end 2026-02-08 --walkforward --force` for all. After A1, run A2-A5 sweeps in parallel. Then B combos, then C random exploration. Compare results with the SQL query in the handoff.

- P1: **Grade Feb 9 and verify Feb 10.** Grading was blocked in Session 179 (raw data not scraped yet). Check if raw data exists now, trigger grading, verify Feb 10 live predictions have all 4 models.

- P2: **Analyze experiment results.** The key metrics: `n_3plus` > 50 (enough picks), `hr_3plus` >= 58% (profitable), walk-forward stability, vegas_points_line importance decreasing with dampening. If a weighted model beats both champion and Jan 31 defaults, consider shadow deployment.

Session 179B context:
- Built 16 new CLI flags: --no-vegas, --residual, --two-stage, --quantile-alpha, --exclude-features, --feature-weights, --category-weight, --rsm, --grow-policy, --min-data-in-leaf, --bootstrap, --subsample, --random-strength, --loss-function
- 9 feature categories defined for --category-weight: recent_performance, composite, derived, matchup, shot_zone, team_context, vegas, opponent_history, minutes_efficiency
- Retrain paradox: vegas_points_line is 30%+ importance, retrained models track Vegas too closely (4-6 edge 3+ picks vs hundreds). Feature weighting explores the gray area.
- Champion decaying (49.8% HR, below breakeven). Jan 31 defaults leads at 54.8% but only 5 days of data.
- Bookmaker expansion: OddsAPI scrapers now query 6 sportsbooks (was 2).
- ML training concepts guide written at docs/08-projects/current/session-179-validation-and-retrain/02-ML-TRAINING-CONCEPTS-GUIDE.md

Use agents in parallel where possible.
