# Processor Reference Cards - Quick Navigation

**Last Updated**: 2025-11-15
**Purpose**: Fast reference for all NBA stats pipeline processors

---

## What Are Processor Cards?

**Quick reference cards** (1-2 pages) for rapid lookups during:
- Daily operations and monitoring
- Debugging production issues
- Onboarding new team members
- Quick handoffs between developers

**Each card includes**:
- ✅ Verified code metrics (lines, fields, tests)
- ✅ Dependencies and consumers
- ✅ Key calculations with examples
- ✅ Health check queries
- ✅ Common issues and fixes
- ✅ Monitoring alerts

---

## Workflow Cards (End-to-End)

**Quick workflow references** showing how processors work together:

| Workflow | Purpose | Use Case |
|----------|---------|----------|
| [**Daily Processing Timeline**](workflow-daily-processing-timeline.md) | Complete orchestration sequence (11 PM → 6 AM) | Understanding nightly pipeline, debugging timing issues |
| [**Real-Time Prediction Flow**](workflow-realtime-prediction-flow.md) | How odds updates trigger predictions (6 AM - 11 PM) | Understanding Phase 5, optimizing prediction latency |

**What they do**: Show how individual processors coordinate to deliver end-to-end functionality.

---

## Phase 3 Processors (Analytics)

### Game-Level Analytics

| # | Processor | Priority | Schedule | Duration | Status |
|---|-----------|----------|----------|----------|--------|
| 1 | [**Player Game Summary**](phase3-player-game-summary.md) | High | After each game | 2-5 min | ✅ Production |
| 2 | [**Team Offense Game Summary**](phase3-team-offense-game-summary.md) | High | After each game | 1-2 min | ✅ Production |
| 3 | [**Team Defense Game Summary**](phase3-team-defense-game-summary.md) | High | After each game | 2-3 min | ✅ Production |

**What they do**: Transform raw Phase 2 game data into clean per-game analytics records.

---

### Forward-Looking Context

| # | Processor | Priority | Schedule | Duration | Status |
|---|-----------|----------|----------|----------|--------|
| 4 | [**Upcoming Player Game Context**](phase3-upcoming-player-game-context.md) | High | Multiple daily | 3-5 min | ✅ Production |
| 5 | [**Upcoming Team Game Context**](phase3-upcoming-team-game-context.md) | High | Multiple daily | 1-2 min | ✅ Production |

**What they do**: Calculate context for TODAY'S games (fatigue, streaks, betting lines).

**Critical**: Run multiple times daily (6 AM, noon, 6 PM, line changes) for real-time predictions.

---

## Phase 5 Predictions (ML Models)

### Prediction Coordinator & Worker

| # | System | Schedule | Duration | Status |
|---|--------|----------|----------|--------|
| 11 | [**Prediction Coordinator**](phase5-prediction-coordinator.md) | 6:15 AM + real-time | 2-5 min (batch) | ✅ Deployed |

**What it does**: Generates player points predictions using 5 ML models with ensemble weighting.

**Models Included:**
1. **Moving Average Baseline** (349 lines) - Simple, reliable baseline
2. **XGBoost V1** (426 lines) - Primary ML model (using mock, needs training)
3. **Zone Matchup V1** (441 lines) - Shot zone analysis predictions
4. **Similarity Balanced V1** (543 lines) - Pattern matching similar players
5. **Ensemble V1** (486 lines) - Confidence-weighted combination

**Architecture**: Coordinator-worker pattern
- Coordinator: Orchestrates daily batch + real-time updates
- Workers: Run 5 prediction systems in parallel
- Output: Ensemble predictions with OVER/UNDER/PASS recommendations

**Status**: Code 100% complete (not deployed, needs XGBoost training)

---

## Phase 4 Processors (Precompute)

### Nightly Precompute (Performance Optimization)

**Runs**: 11:00 PM - 12:00 AM sequence
**Purpose**: Pre-aggregate expensive calculations once, reuse all day

| # | Processor | Priority | Schedule | Duration | Status |
|---|-----------|----------|----------|----------|--------|
| 6 | [**Team Defense Zone Analysis**](phase4-team-defense-zone-analysis.md) | High | 11:00 PM | ~2 min | ✅ Production |
| 7 | [**Player Shot Zone Analysis**](phase4-player-shot-zone-analysis.md) | High | 11:15 PM | 5-8 min | ✅ Production |
| 8 | [**Player Composite Factors**](phase4-player-composite-factors.md) | High | 11:30 PM | 10-15 min | ✅ Production |
| 9 | [**Player Daily Cache**](phase4-player-daily-cache.md) | Medium | 12:00 AM | 5-10 min | ✅ Production |
| 10 | [**ML Feature Store V2**](phase4-ml-feature-store-v2.md) | High | 12:00 AM | ~2 min | ✅ Production |

**Execution Order**:
```
11:00 PM: Team Defense Zone (P1) ──┐
11:15 PM: Player Shot Zone (P2) ───┼─→ 11:30 PM: Player Composite (P3) ──┐
                                                                          ├─→ 12:00 AM: Daily Cache (P4)
                                                                          └─→ 12:00 AM: ML Feature Store (P5)
```

---

## Quick Lookup by Need

### "I need to debug production issues"

**Symptom** → **Check This Card**

- Missing player stats → [Player Game Summary](phase3-player-game-summary.md)
- Wrong pace/usage calculations → [Team Offense](phase3-team-offense-game-summary.md)
- Defensive matchups incorrect → [Team Defense](phase3-team-defense-game-summary.md)
- Fatigue/rest issues → [Upcoming Player Context](phase3-upcoming-player-game-context.md)
- Betting lines missing → [Upcoming Team Context](phase3-upcoming-team-game-context.md)
- Shot zone matchups wrong → [Team Defense Zone](phase4-team-defense-zone-analysis.md) or [Player Shot Zone](phase4-player-shot-zone-analysis.md)
- Composite factors incorrect → [Player Composite Factors](phase4-player-composite-factors.md)
- Cache not updating → [Player Daily Cache](phase4-player-daily-cache.md)
- ML features missing → [ML Feature Store V2](phase4-ml-feature-store-v2.md)
- **Predictions missing/stale** → [**Prediction Coordinator**](phase5-prediction-coordinator.md)
- **All predictions are PASS** → [**Prediction Coordinator**](phase5-prediction-coordinator.md)
- **XGBoost not running** → [**Prediction Coordinator**](phase5-prediction-coordinator.md)

---

### "I need to understand dependencies"

**Phase 3** (reads Phase 2 raw data):
- Player Game Summary: Reads `nbac_gamebook_player_stats`, `bdl_player_boxscores`
- Team Offense: Reads `nbac_team_boxscore`, `nbac_schedule`
- Team Defense: Reads `nbac_team_boxscore`, `nbac_gamebook_player_stats`
- Upcoming Player/Team: Reads `nbac_schedule`, `odds_api_game_lines`

**Phase 4** (reads Phase 3 analytics):
- Team Defense Zone: Reads `team_defense_game_summary`
- Player Shot Zone: Reads `player_game_summary`
- Player Composite: Reads all Phase 3 + P1/P2 Phase 4
- Player Daily Cache: Reads all Phase 3 + P2 Phase 4
- ML Feature Store: Reads all Phase 4 (with Phase 3 fallback)

**Phase 5** (reads Phase 4 features + betting lines):
- Prediction Coordinator: Reads `ml_feature_store_v2`, `player_daily_cache`, `odds_api_player_points_props`
- Output: `player_points_predictions` (ensemble predictions with recommendations)

---

### "I need to check monitoring alerts"

**All processors include**:
- Health check queries (copy-paste ready)
- Alert thresholds (with severity levels)
- Expected value ranges
- Common issues and quick fixes

**Example**: Check all Phase 4 processors completed
```sql
-- Team Defense Zone
SELECT COUNT(*) FROM nba_precompute.team_defense_zone_analysis
WHERE analysis_date = CURRENT_DATE();  -- Expect: 30 teams

-- Player Shot Zone
SELECT COUNT(*) FROM nba_precompute.player_shot_zone_analysis
WHERE analysis_date = CURRENT_DATE();  -- Expect: 400-450 players

-- Player Composite
SELECT COUNT(*) FROM nba_precompute.player_composite_factors
WHERE game_date = CURRENT_DATE();  -- Expect: 100-450 players

-- Player Daily Cache
SELECT COUNT(*) FROM nba_precompute.player_daily_cache
WHERE cache_date = CURRENT_DATE();  -- Expect: 100-450 players

-- ML Feature Store
SELECT COUNT(*) FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE();  -- Expect: 100-450 players

-- Phase 5 Predictions
SELECT
  COUNT(*) as predictions,
  AVG(ensemble_confidence) as avg_confidence,
  COUNT(CASE WHEN recommendation != 'PASS' THEN 1 END) as actionable
FROM nba_predictions.player_points_predictions
WHERE prediction_date = CURRENT_DATE();
-- Expect: 100-450 predictions, 70-80 confidence, 30-150 actionable
```

---

### "I need performance/cost metrics"

| Processor | Duration | BigQuery Cost/Day | Key Optimization |
|-----------|----------|-------------------|------------------|
| Player Game Summary | 2-5 min | ~$0.002 | Multi-source fallback |
| Team Offense | 1-2 min | ~$0.001 | Self-join for opponent |
| Team Defense | 2-3 min | ~$0.001 | Perspective flip |
| Upcoming Player | 3-5 min | ~$0.002 | 30-day rolling window |
| Upcoming Team | 1-2 min | ~$0.001 | Real-time updates |
| Team Defense Zone | ~2 min | ~$0.0003 | 15-game aggregation |
| Player Shot Zone | 5-8 min | ~$0.0025 | 10/20-game windows |
| Player Composite | 10-15 min | ~$0.0003 | Pre-calculated factors |
| **Player Daily Cache** | 5-10 min | **~$0.0013** | **Saves $27/month!** |
| ML Feature Store | ~2 min | ~$0.0003 | Array-based features |

**Total Phase 4 savings**: Player Daily Cache eliminates $27/month in repeated queries.

---

## Documentation Hierarchy

```
📁 docs/
├── 📄 README.md (main project docs)
├── 📁 processor-cards/ (THIS DIRECTORY)
│   ├── 📄 README.md (this file - quick navigation)
│   ├── 📄 workflow-daily-processing-timeline.md
│   ├── 📄 workflow-realtime-prediction-flow.md
│   ├── 📄 phase3-player-game-summary.md
│   ├── 📄 phase3-team-offense-game-summary.md
│   ├── 📄 phase3-team-defense-game-summary.md
│   ├── 📄 phase3-upcoming-player-game-context.md
│   ├── 📄 phase3-upcoming-team-game-context.md
│   ├── 📄 phase4-team-defense-zone-analysis.md
│   ├── 📄 phase4-player-composite-factors.md
│   ├── 📄 phase4-player-shot-zone-analysis.md
│   ├── 📄 phase4-player-daily-cache.md
│   └── 📄 phase4-ml-feature-store-v2.md
├── 📁 templates/
│   └── 📄 processor-reference-card-template.md
├── 📁 orchestration/ (detailed orchestration docs)
├── 📁 architecture/ (detailed architecture docs)
└── 📁 monitoring/ (detailed monitoring guides)
```

**When to use what**:
- 🏃 **Quick lookup** (1-5 min) → **Processor cards** (this directory)
- 🔧 **Troubleshooting** (production issues) → **Operations docs** (see below)
- 📚 **Deep dive** (20-60 min) → Detailed wiki docs (architecture/, orchestration/)
- 🛠️ **Implementation** → Source code + tests

---

## Operations & Troubleshooting

**When production breaks, start here:**

| Guide | Purpose | When to Use |
|-------|---------|-------------|
| [**Cross-Phase Troubleshooting Matrix**](../operations/cross-phase-troubleshooting-matrix.md) | Symptom-based troubleshooting across all phases | First stop when something's broken |
| [Phase 1 Troubleshooting](../orchestration/04-troubleshooting.md) | Orchestration & scraper issues | Phase 1 scrapers failing |
| [Phase 3 Troubleshooting](../processors/04-phase3-troubleshooting.md) | Analytics processor issues | Phase 3 analytics missing/incomplete |
| [Phase 4 Troubleshooting](../processors/07-phase4-troubleshooting.md) | Precompute processor issues | Phase 4 precompute missing/incomplete |
| [Phase 5 Troubleshooting](../predictions/operations/03-troubleshooting.md) | Prediction system issues | Phase 5 predictions missing/low confidence |
| [Grafana Daily Health Check](../monitoring/02-grafana-daily-health-check.md) | Dashboard queries for monitoring | Daily health verification |

**How to use:**
1. **Start** with Cross-Phase Troubleshooting Matrix (symptom → phase diagnosis)
2. **Navigate** to phase-specific troubleshooting doc for detailed fixes
3. **Reference** individual processor cards for specific processor issues

---

## Card Verification Status

All cards verified against actual source code on **2025-11-25**:

| Card | Lines | Fields | Tests | Status |
|------|-------|--------|-------|--------|
| Player Game Summary | ✅ 798 | ✅ 72 | ✅ 96 | Verified |
| Team Offense | ✅ 762 | ✅ 47 | ✅ 97 | Verified |
| Team Defense | ✅ 809 | ✅ 54 | ✅ 39 | Verified |
| Upcoming Player | ✅ 1636 | ✅ 64 | ✅ 89 | Verified |
| Upcoming Team | ✅ 1752 | ✅ 40 | ✅ 83 | Verified |
| Team Defense Zone | ✅ 1146 | ✅ 30 | ✅ 45 | Verified |
| Player Composite | ✅ 1520 | ✅ 39 | ✅ 54 | Verified |
| Player Shot Zone | ✅ 988 | ✅ 32 | ✅ 78 | Verified |
| Player Daily Cache | ✅ 1087 | ✅ 43 | ✅ 50 | Verified |
| ML Feature Store | ✅ 1115 | ✅ 30 | ✅ 158 | Verified |
| **Phase 5 Predictions** | **✅ 2,474** | **~40** | **✅ 11** | **Deployed** |

**All metrics verified** against source code, schemas, and test suites.
**Phase 5**: All 5 models implemented (Moving Avg, XGBoost, Zone, Similarity, Ensemble)

---

## Need More Detail?

Each card links to:
- 📄 **Detailed wiki documentation** (comprehensive guides)
- 🗂️ **Schema definitions** (BigQuery table structures)
- 🧪 **Test suites** (implementation examples)
- 📊 **Related processors** (dependency chains)

---

## Maintenance

**Updating cards**:
1. When code changes significantly, re-verify metrics
2. Update card with new line counts, field counts, test counts
3. Update "Last Updated" and "Verified Against" fields
4. Keep cards concise (1-2 pages max)

**Template**: `/docs/templates/processor-reference-card-template.md`

---

## Contributing

To add a new processor card:
1. Copy template: `cp templates/processor-reference-card-template.md processor-cards/phaseX-new-processor.md`
2. Fill in all sections with verified data
3. Add entry to this README
4. Link from detailed docs

---

**Quick Reference Version**: 1.3
**Created**: 2025-11-15
**Last Updated**: 2025-11-25
**Processors Documented**: 11 (5 Phase 3 + 5 Phase 4 + 1 Phase 5)
**Workflow Cards**: 2 (Daily Timeline + Real-Time Flow)
**Total Cards**: 13
**Total Pages**: ~26 pages (avg 2 pages per card)

**Version History:**
- v1.3 (2025-11-25): Updated line counts to match current codebase, marked Phase 5 as deployed
- v1.2 (2025-11-15): Added Phase 5 Prediction Coordinator card, updated cross-references
- v1.1 (2025-11-15): Added Phase 3-4 processor cards
- v1.0 (2025-11-15): Initial version with workflow cards
