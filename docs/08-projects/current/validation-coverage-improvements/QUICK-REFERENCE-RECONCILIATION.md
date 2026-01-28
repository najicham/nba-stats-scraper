# Cross-Source Reconciliation - Quick Reference

**For**: Data Engineers / Operations Team
**Date**: 2026-01-27

---

## 🚀 Quick Deploy (Copy-Paste)

```bash
# 1. Create view
bq query --use_legacy_sql=false < monitoring/bigquery_views/source_reconciliation_daily.sql

# 2. Create destination table
bq mk --table \
  --time_partitioning_field=run_timestamp \
  --time_partitioning_type=DAY \
  --time_partitioning_expiration=7776000 \
  --clustering_fields=health_status,game_date,team_abbr \
  nba-props-platform:nba_monitoring.source_reconciliation_results \
  run_timestamp:TIMESTAMP,game_date:DATE,game_id:STRING,player_lookup:STRING,player_name:STRING,team_abbr:STRING,starter:BOOLEAN,presence_status:STRING,nbac_points:INT64,nbac_assists:INT64,nbac_rebounds:INT64,bdl_points:INT64,bdl_assists:INT64,bdl_rebounds:INT64,point_diff:INT64,assist_diff:INT64,rebound_diff:INT64,health_status:STRING,discrepancy_summary:STRING,stat_comparison:STRING,checked_at:TIMESTAMP

# 3. Test manually
bq query --use_legacy_sql=false < monitoring/scheduled_queries/source_reconciliation.sql

# 4. Create scheduled query (BigQuery Console)
# Go to: https://console.cloud.google.com/bigquery/scheduled-queries
# Click: + CREATE SCHEDULED QUERY
# Schedule: 0 8 * * * (8 AM daily)
# Paste query from: monitoring/scheduled_queries/source_reconciliation.sql
```

---

## 📊 Daily Check (via /validate-daily)

Run `/validate-daily` for yesterday's results - Phase 3C will show:

```
### Phase 3C: Cross-Source Reconciliation

| Status | Count | % |
|--------|-------|---|
| MATCH  | 280   | 96% ✅
| MINOR_DIFF | 10 | 3% ⚪
| WARNING | 2    | 1% 🟡
| CRITICAL | 0   | 0% ✅
```

**Expected**: 95%+ MATCH, 0 CRITICAL

---

## 🔍 Manual Queries

### Check Today's Summary
```sql
SELECT health_status, COUNT(*) as count
FROM `nba-props-platform.nba_monitoring.source_reconciliation_daily`
GROUP BY health_status
ORDER BY FIELD(health_status, 'CRITICAL', 'WARNING', 'MINOR_DIFF', 'MATCH');
```

### View Critical Issues
```sql
SELECT player_name, team_abbr, discrepancy_summary, stat_comparison
FROM `nba-props-platform.nba_monitoring.source_reconciliation_daily`
WHERE health_status = 'CRITICAL'
ORDER BY point_diff DESC;
```

### Historical Trend (Last 7 Days)
```sql
SELECT
  DATE(run_timestamp) as date,
  health_status,
  COUNT(*) as count
FROM `nba-props-platform.nba_monitoring.source_reconciliation_results`
WHERE DATE(run_timestamp) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY date, health_status
ORDER BY date DESC;
```

---

## 🚨 Alert Thresholds

| Status | Threshold | Action |
|--------|-----------|--------|
| **MATCH** | ≥95% | ✅ All good |
| **MINOR_DIFF** | <5% | ⚪ Note only |
| **WARNING** | <1% | 🟡 Investigate |
| **CRITICAL** | 0% | 🔴 Immediate |

---

## 🔧 Troubleshooting

### "No data available"
- **Cause**: No games yesterday OR scrapers didn't run
- **Check**: `bq query "SELECT COUNT(*) FROM nba_raw.bdl_player_boxscores WHERE game_date = DATE_SUB(CURRENT_DATE(), 1)"`
- **Action**: Wait for scrapers to complete

### Match rate <95%
- **Check**: Did both scrapers run? (`nbac_gamebook`, `bdl_player_boxscores`)
- **Check**: Player name mapping issues? (recent trades?)
- **Action**: Review scraper logs, check player_lookup normalization

### CRITICAL issues found
- **Remember**: NBA.com is source of truth
- **Check**: View specific player stats in both sources
- **Check**: Is it systematic (all games) or isolated (one player)?
- **Action**: Investigate source, not necessarily data error

---

## 📁 Files Reference

| File | Purpose |
|------|---------|
| `monitoring/bigquery_views/source_reconciliation_daily.sql` | View (always yesterday) |
| `monitoring/scheduled_queries/source_reconciliation.sql` | Scheduled query |
| `.claude/skills/validate-daily/SKILL.md` | Phase 3C section |

**Full docs**: `docs/08-projects/current/validation-coverage-improvements/04-CROSS-SOURCE-RECONCILIATION-SETUP.md`

---

## 🎯 Key Concepts

**player_lookup**: Normalized player name (joins both sources)
- Example: `lebronjames` (not `LeBron James`)
- Handles diacritics, suffixes, punctuation

**Source Priority**:
1. NBA.com (official, source of truth)
2. BDL (primary analytics source)
3. Reconciliation validates BDL reliability

**Scheduled Run**: 8 AM ET daily (after overnight processing)

---

## ✅ Success Indicators

Daily validation shows:
- ✅ 95%+ MATCH rate
- ✅ 0 CRITICAL issues
- ✅ <1% WARNING issues
- ✅ Scheduled query ran successfully

---

**Need Help?** See full setup guide: `04-CROSS-SOURCE-RECONCILIATION-SETUP.md`
