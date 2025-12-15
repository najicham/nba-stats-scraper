# Trends v2 Exporters - Implementation TODO

**Created:** 2024-12-14
**Status:** Ready for Implementation

---

## Phase 1: Core Infrastructure

### 1.1 Base Setup
- [ ] **Create trends exporter base class**
  - File: `data_processors/publishing/trends_base_exporter.py`
  - Extend `BaseExporter` with trends-specific helpers
  - Add hit rate calculation utilities
  - Add significance level computation
  - Add time period filtering (7d, 14d, 30d, season)

- [ ] **Create hit rate calculation view/helper**
  - File: `shared/queries/hit_rate_queries.py`
  - Query to join `bettingpros_player_points_props` with `player_game_summary`
  - Return: player_lookup, game_date, prop_line, actual_points, hit (bool), margin

- [ ] **Create archetype classification helper**
  - File: `shared/queries/archetype_queries.py`
  - Classify players by years-in-league, usage_rate, ppg
  - Return: player_lookup, archetype, years_in_league, usage_rate, season_ppg

### 1.2 Unit Tests - Infrastructure
- [ ] **Test hit rate calculation**
  - File: `tests/unit/publishing/test_hit_rate_calculation.py`
  - Test: correct hit/miss determination
  - Test: margin calculation
  - Test: handling missing prop lines

- [ ] **Test archetype classification**
  - File: `tests/unit/publishing/test_archetype_classification.py`
  - Test: veteran_star classification
  - Test: prime_star classification
  - Test: young_star classification
  - Test: edge cases (missing data)

---

## Phase 2: Daily Exporters (Critical Priority)

### 2.1 Who's Hot/Cold Exporter
- [ ] **Create WhosHotColdExporter**
  - File: `data_processors/publishing/whos_hot_cold_exporter.py`
  - Output: `/v1/trends/whos-hot-v2.json`
  - Features:
    - [ ] Heat score algorithm (50% hit rate + 25% streak + 25% margin)
    - [ ] Hot players list (top 10 by heat score)
    - [ ] Cold players list (bottom 10 by heat score)
    - [ ] Time period support (7d, 14d, 30d, season)
    - [ ] Playing tonight flag with game info
    - [ ] Current streak tracking

- [ ] **Unit Tests - WhosHotColdExporter**
  - File: `tests/unit/publishing/test_whos_hot_cold_exporter.py`
  - Test: heat score calculation
  - Test: hot/cold player ranking
  - Test: streak detection
  - Test: playing tonight enrichment
  - Test: time period filtering
  - Test: minimum games threshold

### 2.2 Bounce-Back Watch Exporter
- [ ] **Create BounceBackExporter**
  - File: `data_processors/publishing/bounce_back_exporter.py`
  - Output: `/v1/trends/bounce-back.json`
  - Features:
    - [ ] Identify players 10+ points below season avg in last game
    - [ ] Calculate career bounce-back rate (min 15 situations)
    - [ ] Filter to players with games today
    - [ ] Include opponent defense rank
    - [ ] Significance level calculation
    - [ ] League baseline stats

- [ ] **Unit Tests - BounceBackExporter**
  - File: `tests/unit/publishing/test_bounce_back_exporter.py`
  - Test: underperformance detection
  - Test: bounce-back rate calculation
  - Test: minimum sample threshold (15 games)
  - Test: significance level assignment
  - Test: league baseline computation

---

## Phase 3: Weekly Exporters (High Priority)

### 3.1 What Matters Most Exporter
- [ ] **Create WhatMattersExporter**
  - File: `data_processors/publishing/what_matters_exporter.py`
  - Output: `/v1/trends/what-matters.json`
  - Features:
    - [ ] Archetype classification for all players
    - [ ] Rest impact by archetype
    - [ ] Home/away impact by archetype
    - [ ] B2B impact by archetype
    - [ ] Over rate calculation per factor/archetype
    - [ ] Sample size and significance
    - [ ] Example players per archetype

- [ ] **Unit Tests - WhatMattersExporter**
  - File: `tests/unit/publishing/test_what_matters_exporter.py`
  - Test: archetype grouping
  - Test: factor impact calculation
  - Test: over rate by archetype
  - Test: significance determination

### 3.2 Team Tendencies Exporter
- [ ] **Create TeamTendenciesExporter**
  - File: `data_processors/publishing/team_tendencies_exporter.py`
  - Output: `/v1/trends/team-tendencies.json`
  - Features:
    - [ ] Pace kings/grinders (top/bottom 5 by pace)
    - [ ] Defense by shot profile (interior/perimeter/mid-range)
    - [ ] Home/away extremes
    - [ ] B2B vulnerability rankings
    - [ ] Over/under rates per tendency

- [ ] **Unit Tests - TeamTendenciesExporter**
  - File: `tests/unit/publishing/test_team_tendencies_exporter.py`
  - Test: pace ranking
  - Test: defense by shot profile
  - Test: home/away differential
  - Test: B2B impact calculation

### 3.3 Quick Hits Exporter
- [ ] **Create QuickHitsExporter**
  - File: `data_processors/publishing/quick_hits_exporter.py`
  - Output: `/v1/trends/quick-hits.json`
  - Features:
    - [ ] 8 rotating quick stats
    - [ ] Categories: day_of_week, situational, injury, team, league
    - [ ] Sample size for each stat
    - [ ] Positive/negative indicator

- [ ] **Unit Tests - QuickHitsExporter**
  - File: `tests/unit/publishing/test_quick_hits_exporter.py`
  - Test: stat generation
  - Test: category diversity
  - Test: sample size inclusion

---

## Phase 4: Monthly Exporter (Low Priority)

### 4.1 Deep Dive Promo Exporter
- [ ] **Create DeepDiveExporter**
  - File: `data_processors/publishing/deep_dive_exporter.py`
  - Output: `/v1/trends/deep-dive-current.json`
  - Features:
    - [ ] Monthly featured analysis promo
    - [ ] Hero stat with context
    - [ ] Slug for deep dive page link

- [ ] **Unit Tests - DeepDiveExporter**
  - File: `tests/unit/publishing/test_deep_dive_exporter.py`
  - Test: promo generation

---

## Phase 5: Integration & CLI

### 5.1 CLI Updates
- [ ] **Add trends exporters to daily_export.py**
  - File: `backfill_jobs/publishing/daily_export.py`
  - Add: `--only trends-daily` (whos-hot, bounce-back)
  - Add: `--only trends-weekly` (what-matters, team-tendencies, quick-hits)
  - Add: `--only trends-monthly` (deep-dive)
  - Add: `--only trends-all` (all trends exporters)

- [ ] **Create dedicated trends export script**
  - File: `bin/export_trends.sh`
  - Daily, weekly, monthly modes
  - Logging and error handling

### 5.2 Integration Tests
- [ ] **Test full trends export pipeline**
  - File: `tests/integration/test_trends_export.py`
  - Test: all exporters generate valid JSON
  - Test: GCS upload succeeds
  - Test: JSON schema validation
  - Test: refresh scheduling

---

## Phase 6: Scheduling & Deployment

### 6.1 Cloud Scheduler Setup
- [ ] **Create daily trends job**
  - Schedule: Daily 6 AM ET
  - Exporters: whos-hot-v2, bounce-back
  - Pub/Sub topic: `trends-daily-export`

- [ ] **Create weekly trends job (Monday)**
  - Schedule: Monday 6 AM ET
  - Exporters: what-matters, team-tendencies
  - Pub/Sub topic: `trends-weekly-export`

- [ ] **Create weekly quick-hits job (Wednesday)**
  - Schedule: Wednesday 8 AM ET
  - Exporters: quick-hits
  - Pub/Sub topic: `trends-quickhits-export`

- [ ] **Create monthly trends job**
  - Schedule: 1st of month 6 AM ET
  - Exporters: deep-dive
  - Pub/Sub topic: `trends-monthly-export`

### 6.2 Monitoring & Alerting
- [ ] **Add trends export metrics to Grafana**
  - Export duration per exporter
  - Record counts
  - Error rates

- [ ] **Configure alerting**
  - Alert if daily export fails
  - Alert if export takes >5 minutes

---

## Phase 7: Documentation

### 7.1 Code Documentation
- [ ] **Add docstrings to all exporters**
- [ ] **Add inline comments for complex queries**
- [ ] **Update module __init__.py files**

### 7.2 Operational Documentation
- [ ] **Create trends export runbook**
  - File: `docs/02-operations/runbooks/trends-export.md`
  - Manual export commands
  - Troubleshooting guide
  - Backfill procedures

- [ ] **Update API documentation**
  - Document all `/v1/trends/*` endpoints
  - JSON schema examples
  - Refresh schedules

---

## Quick Reference - Files to Create

```
data_processors/publishing/
├── trends_base_exporter.py         # NEW - Base class
├── whos_hot_cold_exporter.py       # NEW - Daily
├── bounce_back_exporter.py         # NEW - Daily
├── what_matters_exporter.py        # NEW - Weekly
├── team_tendencies_exporter.py     # NEW - Bi-weekly
├── quick_hits_exporter.py          # NEW - Weekly
└── deep_dive_exporter.py           # NEW - Monthly

shared/queries/
├── hit_rate_queries.py             # NEW - Hit rate helpers
└── archetype_queries.py            # NEW - Archetype helpers

tests/unit/publishing/
├── test_whos_hot_cold_exporter.py  # NEW
├── test_bounce_back_exporter.py    # NEW
├── test_what_matters_exporter.py   # NEW
├── test_team_tendencies_exporter.py # NEW
├── test_quick_hits_exporter.py     # NEW
├── test_deep_dive_exporter.py      # NEW
├── test_hit_rate_calculation.py    # NEW
└── test_archetype_classification.py # NEW

tests/integration/
└── test_trends_export.py           # NEW

docs/02-operations/runbooks/
└── trends-export.md                # NEW
```

---

## Estimated Effort

| Phase | Tasks | Effort |
|-------|-------|--------|
| Phase 1: Infrastructure | 6 tasks | 3-4 hrs |
| Phase 2: Daily Exporters | 4 tasks | 6-8 hrs |
| Phase 3: Weekly Exporters | 6 tasks | 8-10 hrs |
| Phase 4: Monthly Exporter | 2 tasks | 1-2 hrs |
| Phase 5: Integration & CLI | 4 tasks | 2-3 hrs |
| Phase 6: Scheduling | 6 tasks | 2-3 hrs |
| Phase 7: Documentation | 4 tasks | 2-3 hrs |
| **Total** | **32 tasks** | **24-33 hrs** |

---

## Dependencies

- Phase 2 depends on Phase 1 (infrastructure)
- Phase 3 depends on Phase 1
- Phase 5 depends on Phases 2-4
- Phase 6 depends on Phase 5

---

## Progress Tracking

**Last Updated:** 2024-12-14

| Phase | Status | Completion |
|-------|--------|------------|
| Phase 1 | Not Started | 0% |
| Phase 2 | Not Started | 0% |
| Phase 3 | Not Started | 0% |
| Phase 4 | Not Started | 0% |
| Phase 5 | Not Started | 0% |
| Phase 6 | Not Started | 0% |
| Phase 7 | Not Started | 0% |
| **Overall** | **Not Started** | **0%** |
