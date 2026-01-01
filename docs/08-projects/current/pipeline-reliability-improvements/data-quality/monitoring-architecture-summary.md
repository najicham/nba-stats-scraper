# Data Completeness Architecture - Visual Summary

## 🎯 The Problem We're Solving

```
Current State:
  Schedule → Scraper → GCS → Processor → BigQuery
                ↓
           (may be empty)
                ↓
         No validation!
                ↓
      Discover days later ❌

New State:
  Schedule → Scraper → Validator → GCS → Processor → BigQuery
                ↓         ↓
           (log)    (compare)
                ↓         ↓
           Monitoring   Alert
                ↓         ↓
          Analytics   Action
```

---

## 🏗️ Three-Layer Defense

### Layer 1: Real-Time Scrape Validation (Seconds)
```
┌─────────────────────────────────────────┐
│  Scraper Executes                       │
│  ├─ Get expected games from schedule    │
│  ├─ Call API                            │
│  ├─ Compare: expected vs actual         │
│  ├─ Log to scrape_execution_log table   │
│  └─ Alert if empty/partial              │
└─────────────────────────────────────────┘
         ↓
    ⚡ IMMEDIATE ALERT if empty response
```

**Detects:** Empty API responses, partial data
**Time to Alert:** <1 minute
**Action:** Human investigates, may retry

---

### Layer 2: Game-Level Completeness (Minutes-Hours)
```
┌─────────────────────────────────────────┐
│  Completeness Checker (runs hourly)     │
│  ├─ Get scheduled games                 │
│  ├─ Check BDL data                      │
│  ├─ Check NBA.com data                  │
│  ├─ Check Odds API data                 │
│  ├─ Update game_completeness table      │
│  └─ Alert on incomplete games           │
└─────────────────────────────────────────┘
         ↓
    🔔 ALERT if games incomplete
```

**Detects:** Missing games across sources, partial coverage
**Time to Alert:** <1 hour
**Action:** Triggers backfill if data available

---

### Layer 3: Daily Audit & Backfill (Daily)
```
┌─────────────────────────────────────────┐
│  Daily Auditor (runs 6 AM ET)           │
│  ├─ Check last 7 days completeness      │
│  ├─ Identify patterns/trends            │
│  ├─ Generate quality report             │
│  └─ Alert on persistent issues          │
└─────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────┐
│  Intelligent Backfiller (runs 7 AM ET)  │
│  ├─ Get incomplete games < 30 days      │
│  ├─ Check if API now has data           │
│  ├─ Trigger backfill scrape              │
│  └─ Update backfill tracking            │
└─────────────────────────────────────────┘
         ↓
    🔄 AUTO-RECOVERY from temporary outages
```

**Detects:** Multi-day patterns, chronic issues
**Time to Alert:** 24 hours
**Action:** Automatic backfill, trend analysis

---

## 📊 Key Tables

### 1. `nba_monitoring.scrape_execution_log`
**Purpose:** Log every scrape attempt
**Updated:** Real-time (during scrape)
**Size:** ~100KB/day
**Retention:** 30 days

```
Example Row:
{
  "execution_id": "abc-123",
  "scraper_name": "bdl_live_box_scores",
  "date_scraped": "2025-12-30",
  "games_expected": 4,
  "games_returned": 0,  ← Empty response!
  "status": "empty_response",
  "alert_sent": true
}
```

### 2. `nba_monitoring.game_data_completeness`
**Purpose:** Track each game across all sources
**Updated:** Hourly + Daily
**Size:** ~1KB/game
**Retention:** Forever

```
Example Row:
{
  "game_id": "0022500461",
  "game_date": "2025-12-30",
  "in_schedule": true,
  "in_bdl": false,  ← Missing!
  "in_nbacom_gamebook": true,
  "is_complete": false,
  "missing_sources": ["bdl_boxscores"],
  "completeness_score": 75.0
}
```

---

## 🚨 Alert Flow

```
Issue Detected
      ↓
Determine Severity
      ↓
   ┌──────────┬──────────┬──────────┐
   ↓          ↓          ↓          ↓
Critical   Warning    Info     None
   ↓          ↓          ↓          ↓
Slack      Slack     Log      Continue
Email      Email     Only
PagerDuty
```

### Severity Matrix

| Days Old | Missing Source | Severity |
|----------|----------------|----------|
| 0-2      | Critical (BDL, NBA.com) | 🔴 Critical |
| 0-2      | Non-critical (Odds) | 🟡 Warning |
| 3-7      | Any source | 🟡 Warning |
| 7+       | Any source | 🔵 Info |

---

## 🔄 Backfill Flow

```
Daily Backfiller Runs
      ↓
Get Incomplete Games
      ↓
For Each Game:
  ├─ Check if API has data now?
  │    ├─ YES → Trigger scrape
  │    └─ NO → Skip (log)
  ↓
Scrape Executes
  ↓
Data → GCS → BigQuery
  ↓
Update Completeness Table
  ↓
Game now complete? ✅
```

**Smart Features:**
- Only retries if API has data (no wasted effort)
- Exponential backoff (1h, 6h, 24h)
- Max 3 attempts before manual intervention
- Tracks success rate per source

---

## 📈 Monitoring Dashboard (Future)

```
┌─────────────────────────────────────────┐
│  Data Quality Dashboard                 │
├─────────────────────────────────────────┤
│  TODAY                                  │
│  ✅ 9/9 games complete                  │
│  ✅ 0 alerts                            │
│                                         │
│  LAST 7 DAYS                            │
│  ⚠️  2/63 games incomplete (96.8%)      │
│  📊 BDL: 96.8%, NBA.com: 100%          │
│                                         │
│  TRENDS                                 │
│  📉 BDL reliability: 91% (↓ 9% vs avg) │
│  📈 Backfill success: 85%               │
│                                         │
│  ACTIVE ISSUES                          │
│  🔴 Dec 30: DET@LAL missing (backfill pending)
│  🔴 Dec 30: SAC@LAC missing (backfill pending)
└─────────────────────────────────────────┘
```

---

## ⏱️ Implementation Timeline

### Phase 1: Today (1 hour)
```
[✅] Design architecture
[⏳] Backfill Dec 30 & Nov 10-12  ← YOU ARE HERE
[  ] Create completeness table
[  ] Baseline check
```

### Phase 2: Tomorrow (3 hours)
```
[  ] Build daily completeness checker
[  ] Deploy to Cloud Functions
[  ] Test alerts
```

### Phase 3: This Week (6 hours)
```
[  ] Create scrape_execution_log table
[  ] Modify scrapers (add logging)
[  ] Deploy real-time validation
```

### Phase 4: Next Week (8 hours)
```
[  ] Build intelligent backfiller
[  ] Deploy daily backfill service
[  ] Monitor & tune
```

**Total Effort:** ~18 hours over 2 weeks

---

## 💰 Cost Impact

| Component | Storage | Compute | Total/Month |
|-----------|---------|---------|-------------|
| Scrape logs | $0.08 | - | $0.08 |
| Completeness table | $0.003 | - | $0.003 |
| Daily checker | - | $0.00002 | $0.00002 |
| Backfiller | - | $0.00004 | $0.00004 |
| Queries | $0.02 | - | $0.02 |
| **TOTAL** | | | **~$0.15/month** |

**Negligible cost increase!**

---

## ✅ Success Metrics

### Week 1
- [x] 100% of last 7 days games accounted for
- [ ] Missing games detected within 24 hours
- [ ] Manual backfill process < 15 minutes

### Month 1
- [ ] Missing games detected within 1 hour
- [ ] 90% of missing games auto-backfilled
- [ ] Zero critical alerts >48 hours old

### Quarter 1
- [ ] 99.9% completeness across all sources
- [ ] Mean time to detect (MTTD) < 5 minutes
- [ ] Mean time to recovery (MTTR) < 1 hour
- [ ] Zero manual interventions

---

## 🎯 Key Takeaways

1. **Three-layer defense** catches issues at different stages
2. **Real-time validation** in scrapers (immediate detection)
3. **Game-level tracking** across all sources (completeness)
4. **Intelligent backfill** recovers automatically
5. **Severity-based alerts** reduces noise
6. **Negligible cost** (~$0.15/month)
7. **Self-healing** pipeline reduces manual work

**Bottom Line:** Know immediately when data is missing, recover automatically when possible, track everything for analysis.

---

## 🚀 Next Action

**Execute Phase 1 backfill:**
→ See `/tmp/immediate_backfill_plan.md`
→ Estimated time: 30-45 minutes
→ Recovers 29 missing games

**Ready to start?**
