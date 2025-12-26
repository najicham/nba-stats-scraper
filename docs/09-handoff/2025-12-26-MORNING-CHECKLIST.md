# Morning Checklist - December 26, 2025

## Quick Verification (5 minutes)

```bash
# 1. Run health check
bin/monitoring/quick_pipeline_check.sh

# 2. Verify all 5 Christmas games collected
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT game_id) as games, COUNT(*) as player_rows
FROM nba_raw.bdl_player_boxscores
WHERE game_date = '2025-12-25'"
# Expected: 5 games, ~170 player rows

# 3. Check for overnight errors
gcloud logging read 'severity>=ERROR' --limit=10 --freshness=8h

# 4. Verify email alerting worked (no more "No recipients" warnings)
gcloud logging read '"No recipients"' --limit=5 --freshness=8h
# Expected: Empty or only old entries before 7:30 PM ET
```

## Expected Results

| Check | Expected |
|-------|----------|
| Christmas games | 5 games collected |
| BDL player rows | ~170 rows |
| Gamebooks | 5 games in BigQuery |
| Overnight errors | 0 critical |
| Email warnings | None after 7:30 PM |

## If Issues Found

1. **Missing games:** Run `PYTHONPATH=. python scripts/check_data_freshness.py`
2. **Errors:** Check `docs/02-operations/daily-monitoring.md` for fixes
3. **Email still broken:** Verify env vars: `gcloud run services describe nba-phase1-scrapers --region=us-west2 --format="yaml" | grep EMAIL`

## Non-Blocking Issues to Fix Later

- [ ] `is_active` hash field in BDL Active Players processor
- [ ] `bdl_box_scores` table reference in cleanup processor
- [ ] datetime JSON serialization in cleanup BQ insert
- [ ] Investigate deploy script env var issue

---

*Have a good morning!*
