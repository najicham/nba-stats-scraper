# BDL Data Quality Issue - Dec 2025

**Discovery Date:** December 31, 2025
**Severity:** High
**Status:** Backfilled (monitoring solution in progress)

---

## Issue Summary

Ball Don't Lie (BDL) API had multiple outages in November-December 2025, returning empty results during live scraping. BDL later backfilled the data, but our pipeline cannot retroactively capture it without manual intervention.

### Impact
- **Dec 30, 2025:** 2/4 games initially missing (50% coverage)
- **Nov 10-12, 2025:** Complete 3-day outage (0/27 games)
- **Total gaps:** 29 games missing from our database
- **Detection lag:** 1+ days (discovered via analytics processor failures)

### Resolution
- ✅ All missing games backfilled manually on Dec 31
- ⏳ Comprehensive monitoring solution designed (implementation in progress)
- 📧 Email to BDL team drafted (awaiting send)

---

## Related Documents

### Investigation & Analysis
- **BDL Email Draft:** `/tmp/bdl_email_draft.md`
  - Professional email to BDL support documenting issues
  - Includes specific dates, error patterns, and questions
  - Ready to send

- **BDL Inventory Report:** `/tmp/bdl_inventory_summary.md`
  - Complete coverage analysis (2021-2025)
  - 4-season summary: 98.5% overall coverage
  - Current season degradation: 91% (vs 100% previous seasons)

### Backfill Execution
- **Backfill Documentation:** `BACKFILL-2025-12-31-BDL-GAPS.md`
  - Step-by-step record of Dec 31 backfill execution
  - Files created, verification commands
  - Timeline and lessons learned

### Architecture & Solution
- **Full Architecture:** `data-completeness-architecture.md` (30 pages)
  - 3-layer defense system (real-time, hourly, daily)
  - 2 new monitoring tables with schemas
  - Code examples and implementation guide
  - 4-phase roadmap over 2 weeks

- **Visual Summary:** `monitoring-architecture-summary.md`
  - Easy-to-digest overview with diagrams
  - Quick reference for team members
  - Success metrics and timeline

### Verification Tools
- **Verification Checklist:** `/tmp/bdl_verification_checklist.md`
  - Manual testing guide for BDL API
  - Specific games to verify
  - curl and Python commands

- **Verification Results:** `/tmp/bdl_verification_results.json`
  - API test results from Dec 31
  - Confirmed all missing games now available in API

---

## Key Findings

### Root Cause: BDL API Reliability
1. **Empty responses:** API returned `{"data": []}` during outages
2. **Delayed backfill:** BDL added data back to API 1+ days later
3. **No notification:** No way to know when backfill occurs
4. **Pattern emerging:** 2025-26 season shows degraded reliability (91% vs 99-100% previous seasons)

### Gaps in Our Monitoring
1. **No real-time validation:** Scraper doesn't check if response matches expected game count
2. **No game-level tracking:** Only table-level freshness (missed 2/4 games = 50% problem)
3. **No automatic backfill:** Can't recover when API adds data later
4. **Late detection:** Found issue 1+ days after via downstream failures

---

## Proposed Solution

### 3-Layer Defense System

#### Layer 1: Real-Time Scrape Validation (Immediate Detection)
```python
# During every scrape:
expected_games = get_from_schedule(date)
actual_games = scrape_api(date)
if len(actual_games) == 0:
    ALERT_IMMEDIATELY("Empty response")
```
**Time to alert:** <1 minute

#### Layer 2: Game-Level Completeness (Hourly Check)
- Compare schedule vs all data sources
- Alert on incomplete games <2 days old
- Cross-validate BDL vs NBA.com

**Time to alert:** <1 hour

#### Layer 3: Intelligent Backfill (Daily Recovery)
- Check if API now has missing data
- Auto-trigger backfill scrapes
- Track recovery success rate

**Time to recovery:** <24 hours

### Implementation Plan

**Phase 1: This Week (3 hours)**
- Daily completeness checker
- Alert on missing games
- ✅ Backfill completed

**Phase 2: Next Week (6 hours)**
- Real-time scrape validation
- Execution logging table
- Empty response alerts

**Phase 3: Following Week (8 hours)**
- Intelligent backfiller
- Auto-recovery system
- Monitoring dashboard

**Total effort:** ~17 hours
**Cost:** ~$0.15/month (negligible)

---

## Success Metrics

### Week 1 (Current)
- [x] 100% of games from last 7 days accounted for
- [x] Missing games backfilled
- [x] Architecture designed

### Month 1 (Target)
- [ ] Missing games detected within 1 hour
- [ ] 90% of gaps auto-backfilled
- [ ] Zero critical alerts >48 hours old

### Quarter 1 (Goal)
- [ ] 99.9% completeness across all sources
- [ ] Mean time to detect < 5 minutes
- [ ] Mean time to recover < 1 hour
- [ ] Zero manual interventions

---

## Decision Log

### Dec 31, 2025

**Decision 1: Backfill Now**
- **Rationale:** BDL API has data now, may disappear again
- **Action:** Manual backfill executed
- **Result:** 29 games recovered

**Decision 2: Build Comprehensive Solution**
- **Rationale:** This will happen again (pattern suggests ongoing reliability issues)
- **Action:** 3-layer monitoring system designed
- **Timeline:** 2-3 weeks implementation

**Decision 3: Contact BDL**
- **Rationale:** Understand their side, set expectations
- **Action:** Professional email drafted
- **Status:** Ready to send (user approval pending)

**Decision 4: Phased Implementation**
- **Rationale:** Balance urgency vs thoroughness
- **Action:** 4 phases over 2-3 weeks
- **Priority:** Daily checks first, then real-time, then auto-backfill

---

## Current Status

### Completed ✅
- [x] Root cause investigation
- [x] BDL API verification
- [x] Manual backfill execution (Dec 30 & Nov 10-12)
- [x] Comprehensive architecture design
- [x] Documentation created
- [x] BDL email drafted

### In Progress ⏳
- [ ] BigQuery processing verification (files published to Pub/Sub, awaiting processing)
- [ ] BDL email review/send

### Pending 📋
- [ ] Phase 1 implementation (daily completeness checker)
- [ ] Phase 2 implementation (real-time validation)
- [ ] Phase 3 implementation (auto-backfill)
- [ ] Monitoring dashboard

---

## Contact & References

### BDL Communication
- **Email Draft:** `/tmp/bdl_email_draft.md`
- **API Status:** No known status page
- **Support:** TBD (need to find support contact)

### Team Documents
- **Architecture Plan:** `data-completeness-architecture.md`
- **Backfill Log:** `BACKFILL-2025-12-31-BDL-GAPS.md`
- **Visual Guide:** `monitoring-architecture-summary.md`

### Quick Commands

```bash
# Check BDL completeness for recent dates
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(DISTINCT s.game_id) as scheduled,
  COUNT(DISTINCT b.game_id) as in_bdl,
  COUNT(DISTINCT s.game_id) - COUNT(DISTINCT b.game_id) as missing
FROM nba_raw.nbac_schedule s
LEFT JOIN nba_raw.bdl_player_boxscores b
  ON s.game_date = b.game_date
  AND s.home_team_tricode = b.home_team_abbr
  AND s.away_team_tricode = b.away_team_abbr
WHERE s.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND s.game_status_text = 'Final'
GROUP BY game_date
ORDER BY game_date DESC"

# Manual backfill command (if needed again)
python3 /tmp/backfill_bdl.py
```

---

**Last Updated:** December 31, 2025, 8:45 PM PT
**Next Review:** January 1, 2026 (verify Dec 31 games processed)
**Owner:** Data Engineering Team
