# Data Source Redundancy - Quick Reference

## Daily Commands

### Check Source Health
```bash
# Morning health dashboard
./bin/monitoring/morning_health_check.sh

# Cross-source validation (yesterday)
python bin/monitoring/cross_source_validator.py

# BDL quality check
python bin/monitoring/check_bdl_data_quality.py --days 7
```

### Manual Scraping
```bash
# Scrape Basketball Reference (specific date)
python scrapers/basketball_reference/bref_boxscore_scraper.py --date 2026-01-27

# Scrape NBA API BoxScore (specific date)
python scrapers/nba_api_backup/boxscore_traditional_scraper.py --date 2026-01-27

# Run all GCS backups
python scrapers/nba_api_backup/gcs_backup_scrapers.py
```

### Query Discrepancies
```sql
-- Recent discrepancies
SELECT * FROM nba_orchestration.source_discrepancies
WHERE game_date >= CURRENT_DATE() - 7
ORDER BY game_date DESC, severity;

-- Discrepancy summary
SELECT game_date, backup_source, severity, COUNT(*) as count
FROM nba_orchestration.source_discrepancies
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1, 2, 3
ORDER BY 1 DESC;
```

---

## Source Status

| Source | Status | Script | Schedule |
|--------|--------|--------|----------|
| NBA.com Gamebook | ✅ Primary | Existing scrapers | Real-time |
| Basketball Reference | ✅ Backup | `bref_boxscore_scraper.py` | Daily 11 AM UTC |
| NBA API BoxScoreV3 | ✅ Backup | `boxscore_traditional_scraper.py` | Daily 11 AM UTC |
| BDL API | ⚠️ Disabled | `check_bdl_data_quality.py` | Monitoring only |

---

## Alert Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| Minutes difference | >1 min | >3 min |
| Points difference | >1 pt | >2 pts |
| Backup coverage | <90% | <80% |
| BDL mismatch rate | >10% | >15% |
| Data gap age | >6 hours | >24 hours |

---

## Re-Enable BDL

When BDL quality improves (>95% accuracy for 7 days):

```python
# In data_processors/analytics/player_game_summary/player_game_summary_processor.py
USE_BDL_DATA = True  # Change from False
```

---

## Troubleshooting

### Scraper Timeout
```bash
# NBA API needs custom headers - already configured
# If still timing out, check NBA.com status
```

### No Data from BRef
```bash
# Check if Basketball Reference is up
curl -s https://www.basketball-reference.com | head -1

# May be rate limited - wait 5 minutes
```

### Discrepancy Spike
```sql
-- Find specific mismatches
SELECT player_name, discrepancies_json
FROM nba_orchestration.source_discrepancies
WHERE game_date = '2026-01-27'
  AND severity = 'major';
```

---

## Key Files

```
bin/monitoring/
├── cross_source_validator.py    # Compare sources
├── check_bdl_data_quality.py    # BDL monitor
├── bdl_quality_alert.py         # BDL alerts
└── morning_health_check.sh      # Daily dashboard

scrapers/
├── basketball_reference/
│   └── bref_boxscore_scraper.py
└── nba_api_backup/
    ├── boxscore_traditional_scraper.py
    └── gcs_backup_scrapers.py

.github/workflows/
├── daily-source-validation.yml
└── bdl-quality-monitor.yml
```

---

## Contacts

- BigDataBall support: (check their website)
- BDL API: https://www.balldontlie.io
- NBA.com stats: (no public support)
