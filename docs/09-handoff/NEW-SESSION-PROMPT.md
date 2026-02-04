# Prompt for Next Claude Code Session

Copy and paste this into your next Claude Code session:

---

I'm continuing Session 113+ data quality fixes for the NBA prediction system. Please read the comprehensive handoff document first:

```
Read: docs/09-handoff/2026-02-04-SESSION-113-PLUS-COMPLETE-HANDOFF.md
```

## Quick Context

Session 113+ fixed massive data quality issues (DNP pollution affecting 67% of Nov-Jan training data). We've made major progress:

**✅ Complete:**
- Fixed 981 unmarked DNPs in Phase 3
- Improved DNP filter in Phase 4 (commit dd225120)
- Regenerated 73/106 dates in player_daily_cache
- Reprocessed ML features for Dec-Jan-Feb (97-99% fixed)
- Implemented dynamic threshold for shot_zone (commit e06043b9)
- Fixed save_precompute() return bug (commit 241153d3)
- Updated validation skills with 5 new checks

**⏳ Critical Next Steps:**
1. **Deploy bug fixes** (commits 241153d3, e06043b9) to `nba-phase4-precompute-processors`
2. **Regenerate shot_zones** for Nov 4-18 with new dynamic threshold code
3. **Re-run ML feature store** for November to improve from 68% to 95%+
4. **Run final validation** queries to verify fixes
5. **Check all other ML features** for similar early season issues (composite_factors, team_defense, etc.)
6. **Create historical validation plan** for seasons 2022-2025

## Immediate Action

Start with deployment verification:

```bash
# Check what's currently deployed
./bin/whats-deployed.sh

# Compare to latest commits
git log --oneline -5

# If drift detected, deploy Phase 4 fixes
./bin/deploy-service.sh nba-phase4-precompute-processors
```

## Key Files Changed

- `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py` (dynamic threshold)
- `data_processors/precompute/operations/bigquery_save_ops.py` (save bug fix)
- `data_processors/precompute/ml_feature_store/feature_extractor.py` (DNP filter)
- `.claude/skills/spot-check-features/SKILL.md` (validation checks)

## Known Issues

- November ML features: 68% fixed (needs shot_zone regeneration to reach 95%+)
- Nov 27: 0 records (likely off day, investigate if needed)
- Team defense zone: Missing for 2026-01-23 (non-critical)

## Success Criteria

- All services deployed with latest commits
- December-February: >95% match rate between cache and ML features
- November: >90% match rate after shot_zone regeneration
- All validation skill checks passing
- Historical validation plan documented

## Questions to Consider

1. Should we retrain V9 model with cleaned data?
2. How far back should historical validation go?
3. What other ML features need early season fixes?

Let me know if you want me to:
- A) Continue with deployment and November fixes
- B) Focus on historical data validation plan
- C) Check all other ML features first
- D) Something else

---

**Note:** All background agents completed, no tasks pending. Ready for deployment and validation.
