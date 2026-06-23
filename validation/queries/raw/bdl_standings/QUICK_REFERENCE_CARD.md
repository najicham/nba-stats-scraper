# BDL Standings Validation - Quick Reference Card

## 🚀 Daily Routine (9:00 AM PT)

```bash
cd ~/code/nba-stats-scraper
./scripts/validate-bdl-standings daily
```

**✅ Healthy:** Status = "✅ Complete", 30 teams, 15 East/15 West
**🔴 Alert:** Status ≠ Complete → Check logs, re-run scraper

---

## 📅 Weekly Routine (Monday 9:30 AM PT)

```bash
./scripts/validate-bdl-standings weekly      # Coverage check
./scripts/validate-bdl-standings conference  # Rankings validation
./scripts/validate-bdl-standings quality     # Data quality check
```

**✅ Healthy:** 7/7 days, 100% coverage, >95% quality
**⚠️ Warning:** Missing days → Backfill needed

---

## 📊 Monthly Routine (First Monday)

```bash
./scripts/validate-bdl-standings coverage    # Season coverage
```

**✅ Healthy:** >95% monthly coverage
**⚠️ Warning:** <90% coverage → Run `missing` to identify gaps

---

## 🚨 Emergency Commands

```bash
# Find missing dates
./scripts/validate-bdl-standings missing

# Run all validations
./scripts/validate-bdl-standings all

# Export for analysis
./scripts/validate-bdl-standings missing --csv > missing.csv
```

---

## 🔧 Quick Fix Workflow

1. **Identify Issue:** Run `daily` or `missing`
2. **Check Logs:** `gcloud run jobs executions list --job=bdl-standings-scraper`
3. **Check Storage:** `gsutil ls gs://nba-props-data/ball-dont-lie/standings/2024-25/YYYY-MM-DD/`
4. **Re-run Scraper:** `gcloud run jobs execute bdl-standings-scraper --args="--date=YYYY-MM-DD"`
5. **Re-run Processor:** `gcloud run jobs execute bdl-standings-processor --args="--date=YYYY-MM-DD"`
6. **Verify:** Run `daily` again

---

## 📍 Alert Thresholds

| Status | Threshold | Action |
|--------|-----------|--------|
| 🔴 CRITICAL | No data during season | Immediate scraper check |
| 🔴 CRITICAL | Team count ≠ 30 | Check processor logs |
| ⚠️ WARNING | Missing 1-2 days/week | Plan backfill |
| ⚠️ WARNING | Quality <95% | Review data source |
| ⚠️ WARNING | Ranking mismatches | Check BDL API |

---

## 📁 File Locations

```
validation/queries/raw/bdl_standings/     # SQL queries
scripts/validate-bdl-standings            # CLI tool
nba-props-platform.nba_raw.bdl_standings  # Database table
```

---

## 🎯 Success Metrics

- **Daily:** 100% data capture (30 teams)
- **Weekly:** 7/7 days coverage
- **Monthly:** >95% season coverage
- **Quality:** >95% calculation accuracy

---

**Quick Help:** `./scripts/validate-bdl-standings help`
