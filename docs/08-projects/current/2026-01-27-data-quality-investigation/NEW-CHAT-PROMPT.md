# Prompt for New Opus Chat

Copy everything below the line to start a new chat:

---

## Continue NBA Props Platform Data Quality Work

Read the handoff document first:
`docs/08-projects/current/2026-01-27-data-quality-investigation/HANDOFF-CONTINUATION.md`

### Context

A previous Opus session completed extensive work on data quality issues:
- Identified 6 root causes (NULL usage_rate, duplicates, prediction timing, etc.)
- Committed and deployed 4 code fixes to production
- Deployed monitoring Cloud Function with daily alerts
- Created deployment runbook and architecture design
- 29 commits ahead of origin (not pushed yet)

### Current Status

| Metric | Value | Status |
|--------|-------|--------|
| Analytics processor | Revision 00127-ppr | ✅ Deployed with all fixes |
| Monitoring function | Live at 7 PM ET daily | ✅ Deployed |
| Jan 26 usage_rate | 57.8% | ✅ CORRECT (not a bug) |
| Jan 27 predictions | 0 | ❌ Needs trigger |
| Duplicates | 0 | ✅ Fixed |
| Git commits | 29 ahead | ❌ Not pushed |

**Key finding**: 57.8% usage_rate is CORRECT. Players with 0 possessions (DNP/garbage time) should have NULL usage_rate. 100% of players with actual stats have valid usage_rate.

### Your Tasks (Priority Order)

1. **Generate Jan 27 predictions** (most urgent)
   ```bash
   python3 bin/predictions/clear_and_restart_predictions.py --game-date 2026-01-27
   ```
   Then verify predictions > 0

2. **Push commits to origin**
   ```bash
   git log --oneline origin/main..HEAD  # Review 29 commits
   git push origin main
   ```

3. **Backfill historical gaps** (3 dates with incomplete data)
   - Jan 13: 49.7% complete (P1 CRITICAL)
   - Jan 24: 88.5% complete (P2 HIGH)
   - Jan 08: 84.0% complete (P2 HIGH)

   Commands in `HANDOFF-CONTINUATION.md`

4. **Run full validation** to confirm everything works
   ```bash
   /validate-historical 2026-01-01 2026-01-27
   ```

5. **Test monitoring alerts**
   ```bash
   curl "https://data-quality-alerts-f7p3g7f6ya-wl.a.run.app?game_date=2026-01-26&dry_run=true"
   ```

### Key Files

```
docs/08-projects/current/2026-01-27-data-quality-investigation/
├── HANDOFF-CONTINUATION.md     # Start here - full context
├── ROOT-CAUSE-ANALYSIS.md      # Why issues happened
├── ARCHITECTURE-IMPROVEMENTS.md # Future improvements design
├── VALIDATION-REPORT.md        # Current validation status
└── QUICK-START-MONITORING.md   # Quick reference

bin/predictions/
├── fix_stuck_coordinator.py    # If coordinator is stuck
└── clear_and_restart_predictions.py  # Restart predictions

scripts/deploy/
├── deploy-analytics.sh         # If redeployment needed
└── deploy-predictions.sh
```

### What NOT to Do

- Don't try to "fix" 57.8% usage_rate - it's correct
- Don't redeploy analytics processor - already deployed with all fixes
- Don't recreate monitoring function - already live

### Success Criteria

- [ ] Jan 27 predictions > 80
- [ ] Git commits pushed to origin
- [ ] Historical gaps backfilled (Jan 13, 24, 08)
- [ ] Validation passes for Jan 1-27
- [ ] Monitoring alert test successful

### If Something Goes Wrong

1. Check Cloud Run logs: `gcloud logging read "resource.type=cloud_run_revision" --limit=50`
2. Check coordinator status: `python3 bin/predictions/fix_stuck_coordinator.py list`
3. Review deployment docs: `docs/02-operations/DEPLOYMENT.md`
