# Additional Validation Opportunities - Todo List
**Created**: 2026-01-16
**Status**: Brainstorm - Prioritization Needed
**Context**: Beyond the 3 validators already created, what else can we validate?

---

## Overview

We've created 3 core validators:
- ✅ BettingPros props
- ✅ Player game summary analytics
- ✅ Prediction coverage

This document explores **additional validation opportunities** across the entire data pipeline.

---

## Category 1: Raw Data Sources (Phase 1)

### High Priority

#### 1.1 Injury Report Validation
**Two sources to validate**: `nbac_injury_report` + `bdl_injuries`

**Config**: `validation/configs/raw/injury_reports.yaml`

**Validations**:
- [ ] **Peak hour coverage** (5 PM, 8 PM ET on game days)
- [ ] **Player status consistency** (Out, Questionable, Probable, Available)
- [ ] **Cross-source comparison** (NBA.com vs BDL injury discrepancies)
- [ ] **Confidence score tracking** (parsing quality over time)
- [ ] **Status change detection** (intraday injury updates)
- [ ] **Game day injury completeness** (all scheduled games have reports)

**Business Value**: HIGH - Injuries affect predictions and betting lines

**Example Query**:
```sql
-- Verify peak hour coverage
SELECT
  game_date,
  report_hour,
  COUNT(DISTINCT player_lookup) as players_reported,
  AVG(confidence_score) as avg_confidence
FROM nba_raw.nbac_injury_report
WHERE game_date = CURRENT_DATE()
  AND report_hour IN (17, 20)  -- 5 PM, 8 PM ET
GROUP BY game_date, report_hour
HAVING players_reported < 10;  -- Alert if too few
```

#### 1.2 Schedule Validation (Enhanced)
**Existing**: `validation/configs/raw/nbac_schedule.yaml`

**Additional checks to add**:
- [ ] **Game time consistency** (no games scheduled at odd hours like 3 AM)
- [ ] **Probable starters populated** (important for props)
- [ ] **Broadcast info present** (national TV games)
- [ ] **Arena information** (home/away venue consistency)
- [ ] **Postponement tracking** (games moved due to weather, COVID, etc.)
- [ ] **Playoff bracket integrity** (correct seeds, series structure)

#### 1.3 Play-by-Play Validation
**Sources**: `nbac_play_by_play`, `bdb_pbp_scraper`

**Config**: `validation/configs/raw/play_by_play.yaml`

**Validations**:
- [ ] **Event count reasonableness** (200-400 events per game)
- [ ] **Event sequence integrity** (timestamps increasing, no gaps)
- [ ] **Score consistency** (play-by-play score matches final score)
- [ ] **Player participation** (all active players appear in PBP)
- [ ] **Shot chart completeness** (all FG attempts have coordinates)
- [ ] **Critical moments captured** (game-winning shots, buzzer beaters)

**Business Value**: MEDIUM - Useful for advanced analytics

### Medium Priority

#### 1.4 Team Roster Validation
**Source**: `espn_team_roster`

**Validations**:
- [ ] **30 teams present** (all NBA teams have rosters)
- [ ] **Roster size reasonable** (12-17 players per team)
- [ ] **Player positions valid** (G, F, C combinations)
- [ ] **Jersey numbers unique** (no duplicates per team)
- [ ] **Two-way contracts tracked** (roster designation)
- [ ] **Injury list cross-reference** (injured players on roster)

#### 1.5 Referee Assignment Validation
**Source**: `nbac_referee_assignments`

**Validations**:
- [ ] **All games have referees** (3 officials per game)
- [ ] **Referee name consistency** (no typos)
- [ ] **Experience tracking** (games officiated per referee)
- [ ] **Crew chief identification** (lead referee per game)
- [ ] **Historical patterns** (referee assignment fairness)

### Low Priority

#### 1.6 News Pipeline Validation
**Source**: `news_pipeline` (if exists)

**Validations**:
- [ ] **Freshness** (news within 24 hours)
- [ ] **Relevance** (news related to scheduled players/games)
- [ ] **Sentiment analysis** (positive/negative/neutral)
- [ ] **Source diversity** (multiple news sources)

---

## Category 2: Phase 2 Processors Validation

### High Priority

#### 2.1 Gamebook Processor Validation
**Processor**: `NbacGamebookProcessor`

**Config**: `validation/configs/processors/nbac_gamebook.yaml`

**Validations**:
- [ ] **Active vs roster tracking** (R-009 specific validation)
- [ ] **Partial status detection** (data_status field populated correctly)
- [ ] **Player stats completeness** (points, rebounds, assists not null)
- [ ] **DNP tracking** (inactive players marked correctly)
- [ ] **Starter vs bench designation** (starting lineup identified)
- [ ] **Plus/minus calculation** (reasonable values -30 to +30)

**Example Query**:
```sql
-- Validate active vs roster tracking
SELECT
  game_code,
  JSON_EXTRACT_SCALAR(summary, '$.active_records') as active_records,
  JSON_EXTRACT_SCALAR(summary, '$.roster_records') as roster_records,
  records_processed,
  status
FROM nba_reference.processor_run_history
WHERE processor_name = 'NbacGamebookProcessor'
  AND data_date = CURRENT_DATE()
  AND JSON_EXTRACT_SCALAR(summary, '$.active_records') = '0';  -- Alert if 0
```

#### 2.2 Boxscore Processor Validation
**Processors**: `nbac_player_boxscore`, `nbac_team_boxscore`

**Validations**:
- [ ] **Team totals match player totals** (sum of player points = team points)
- [ ] **Minutes played total** (should sum to ~240 per game, or 265+ with OT)
- [ ] **Field goal math** (FGM ≤ FGA, 3PM ≤ FGM, etc.)
- [ ] **Rebound accounting** (ORB + DRB = TRB)
- [ ] **Assist-to-made-field-goal ratio** (reasonable team AST/FGM ratio)
- [ ] **Turnover reasonableness** (8-20 per team typical)

**Example Query**:
```sql
-- Verify team totals match player totals
WITH player_totals AS (
  SELECT
    game_id,
    team_abbr,
    SUM(points) as player_points,
    SUM(rebounds) as player_rebounds
  FROM nba_raw.nbac_player_boxscore
  WHERE game_date = CURRENT_DATE()
  GROUP BY game_id, team_abbr
),
team_totals AS (
  SELECT
    game_id,
    team_abbr,
    team_points,
    team_rebounds
  FROM nba_raw.nbac_team_boxscore
  WHERE game_date = CURRENT_DATE()
)
SELECT
  p.game_id,
  p.team_abbr,
  p.player_points,
  t.team_points,
  ABS(p.player_points - t.team_points) as points_diff
FROM player_totals p
JOIN team_totals t ON p.game_id = t.game_id AND p.team_abbr = t.team_abbr
WHERE ABS(p.player_points - t.team_points) > 2;  -- Alert if mismatch
```

### Medium Priority

#### 2.3 BDL Processor Validation
**Processor**: `bdl_player_boxscores`

**Validations**:
- [ ] **Active players only** (no DNP in BDL data)
- [ ] **Stat comparison with NBA.com** (points, assists, rebounds match)
- [ ] **Game coverage** (all finished games have BDL data)
- [ ] **Latency tracking** (time from game end to BDL availability)
- [ ] **API health** (BDL API uptime and response times)

---

## Category 3: Phase 3 Analytics Validation

### High Priority

#### 3.1 Team Analytics Validation
**Tables**: `team_offense_game_summary`, `team_defense_game_summary`

**Config**: `validation/configs/analytics/team_game_summary.yaml`

**Validations**:
- [ ] **Both teams per game** (offense and defense data for both teams)
- [ ] **Opponent matching** (team A's offense vs team B's defense)
- [ ] **Stat consistency** (offensive rebounds allowed = opponent offensive rebounds)
- [ ] **Four factors calculation** (eFG%, TOV%, ORB%, FTR within ranges)
- [ ] **Pace calculation** (possessions per game 95-105 typical)
- [ ] **Net rating** (offensive rating - defensive rating reasonable)

#### 3.2 Upcoming Game Context Validation
**Table**: `upcoming_team_game_context`

**Validations**:
- [ ] **All scheduled games have context** (rest days, back-to-backs)
- [ ] **Rest calculation accuracy** (days since last game)
- [ ] **Home/away streak tracking** (consecutive home/away games)
- [ ] **Opponent strength** (opponent recent record, injuries)
- [ ] **Travel distance** (if tracked, reasonable values)

### Medium Priority

#### 3.3 Game Referees Analytics
**Table**: `game_referees`

**Validations**:
- [ ] **All games have referee data**
- [ ] **Historical foul patterns** (fouls per game by referee)
- [ ] **Home/away bias detection** (referee impact on home win rate)
- [ ] **Technical foul trends** (certain refs call more techs)

---

## Category 4: Phase 4 ML Features Validation

### High Priority

#### 4.1 ML Feature Quality Validation
**Table**: `nba_ml_features.player_game_features`

**Config**: `validation/configs/ml_features/feature_quality.yaml`

**Validations**:
- [ ] **No NULL critical features** (key features always populated)
- [ ] **No NaN values** (data type consistency)
- [ ] **Feature value ranges** (within expected bounds)
- [ ] **Rolling averages reasonable** (5-game avg close to 10-game avg)
- [ ] **Opponent features present** (opponent defense ratings populated)
- [ ] **Temporal features valid** (rest days, game number in season)

**Example Query**:
```sql
-- Detect NULL or out-of-range features
SELECT
  player_lookup,
  game_date,
  points_avg_last_5,
  points_avg_last_10,
  opponent_def_rating
FROM nba_ml_features.player_game_features
WHERE game_date = CURRENT_DATE()
  AND (
    points_avg_last_5 IS NULL
    OR points_avg_last_10 IS NULL
    OR points_avg_last_5 < 0
    OR points_avg_last_5 > 50
    OR opponent_def_rating IS NULL
  );
```

#### 4.2 Feature Generation Completeness
**Validations**:
- [ ] **All analytics players have features** (coverage check)
- [ ] **Feature generation latency** (time from analytics to features)
- [ ] **Historical features available** (lookback data exists)
- [ ] **Feature version tracking** (which feature set version)

---

## Category 5: Phase 5 Predictions - Advanced Validation

### High Priority

#### 5.1 Individual System Performance
**Beyond aggregate coverage, validate each system individually**

**Config**: `validation/configs/predictions/system_performance.yaml`

**Validations per system**:
- [ ] **Accuracy by game situation** (home/away, rest days, back-to-backs)
- [ ] **Accuracy by player type** (stars vs role players)
- [ ] **Accuracy by prop line range** (high lines vs low lines)
- [ ] **Calibration check** (70% confidence = 70% accuracy?)
- [ ] **Bias detection** (systematically over/under predicting)
- [ ] **Consistency** (stable performance over time)

**Example Query**:
```sql
-- System accuracy by prop line range
SELECT
  system_id,
  CASE
    WHEN predicted_points < 15 THEN 'Low (< 15)'
    WHEN predicted_points < 25 THEN 'Medium (15-25)'
    ELSE 'High (25+)'
  END as line_range,
  COUNT(*) as predictions,
  COUNTIF(is_correct = TRUE) as correct,
  ROUND(100.0 * COUNTIF(is_correct = TRUE) / COUNT(*), 1) as accuracy_pct
FROM nba_predictions.player_prop_predictions
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND grade IS NOT NULL
GROUP BY system_id, line_range
ORDER BY system_id, line_range;
```

#### 5.2 Edge Calculation Validation
**Validations**:
- [ ] **Edge reasonableness** (-5 to +5 points typical)
- [ ] **Edge vs confidence correlation** (high edge = high confidence?)
- [ ] **Edge vs accuracy relationship** (do we win when edge is high?)
- [ ] **Market efficiency** (our edge vs market movement)

#### 5.3 Confidence Calibration
**Validations**:
- [ ] **Calibration curves** (plot confidence vs actual accuracy)
- [ ] **Confidence bucket analysis** (70-80% confidence = 75% accuracy?)
- [ ] **Over-confidence detection** (claiming 95% but only 70% accurate)
- [ ] **Under-confidence detection** (claiming 60% but actually 80% accurate)

**Example Query**:
```sql
-- Confidence calibration check
SELECT
  system_id,
  CASE
    WHEN prediction_confidence < 0.6 THEN '< 60%'
    WHEN prediction_confidence < 0.7 THEN '60-70%'
    WHEN prediction_confidence < 0.8 THEN '70-80%'
    WHEN prediction_confidence < 0.9 THEN '80-90%'
    ELSE '90%+'
  END as confidence_bucket,
  COUNT(*) as predictions,
  COUNTIF(is_correct = TRUE) as correct,
  ROUND(100.0 * COUNTIF(is_correct = TRUE) / COUNT(*), 1) as actual_accuracy
FROM nba_predictions.player_prop_predictions
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
  AND grade IS NOT NULL
GROUP BY system_id, confidence_bucket
ORDER BY system_id, confidence_bucket;
```

### Medium Priority

#### 5.4 Model Drift Detection
**Validations**:
- [ ] **30-day rolling accuracy** (detect degradation over time)
- [ ] **Feature importance changes** (which features matter now vs before)
- [ ] **Prediction distribution shifts** (predicting too high/low lately?)
- [ ] **Seasonality patterns** (performance different in playoffs?)

---

## Category 6: Cross-Source Validations

### High Priority

#### 6.1 BDL vs NBA.com Stat Comparison
**Critical for data quality assurance**

**Config**: `validation/configs/cross_source/bdl_vs_nbac.yaml`

**Validations**:
- [ ] **Points discrepancy** (>2 points = critical issue)
- [ ] **Assists discrepancy** (>2 assists = warning)
- [ ] **Rebounds discrepancy** (>2 rebounds = warning)
- [ ] **Minutes played discrepancy** (>5 minutes = warning)
- [ ] **Systematic bias** (BDL consistently higher/lower?)

**Example Query**:
```sql
-- Cross-source stat comparison
SELECT
  b.game_id,
  b.player_lookup,
  b.points as bdl_points,
  n.points as nbac_points,
  ABS(b.points - n.points) as points_diff,
  b.assists as bdl_assists,
  n.assists as nbac_assists,
  ABS(b.assists - n.assists) as assists_diff
FROM nba_raw.bdl_player_boxscores b
JOIN nba_raw.nbac_gamebook_player_stats n
  ON b.game_id = n.game_id
  AND b.player_lookup = n.player_lookup
WHERE b.game_date = CURRENT_DATE()
  AND (
    ABS(b.points - n.points) > 2
    OR ABS(b.assists - n.assists) > 2
  );
```

#### 6.2 Props Lines Market Comparison
**Detect outlier bookmakers and suspicious movements**

**Validations**:
- [ ] **Consensus line calculation** (median across bookmakers)
- [ ] **Outlier detection** (bookmaker >3 points off consensus)
- [ ] **Line movement tracking** (identify sharp money)
- [ ] **Bookmaker reliability** (which books are most accurate)
- [ ] **Market efficiency** (do lines converge over time?)

**Example Query**:
```sql
-- Detect outlier bookmaker lines
WITH consensus AS (
  SELECT
    player_lookup,
    game_date,
    APPROX_QUANTILES(over_line, 100)[OFFSET(50)] as median_line,
    STDDEV(over_line) as line_stddev
  FROM nba_raw.bettingpros_player_points_props
  WHERE game_date = CURRENT_DATE()
  GROUP BY player_lookup, game_date
)
SELECT
  p.player_lookup,
  p.bookmaker,
  p.over_line,
  c.median_line,
  ABS(p.over_line - c.median_line) as diff_from_consensus,
  c.line_stddev
FROM nba_raw.bettingpros_player_points_props p
JOIN consensus c
  ON p.player_lookup = c.player_lookup
  AND p.game_date = c.game_date
WHERE ABS(p.over_line - c.median_line) > 3  -- >3 points off consensus
ORDER BY diff_from_consensus DESC;
```

### Medium Priority

#### 6.3 Schedule Consistency Across Sources
**Validations**:
- [ ] **Game time agreement** (all sources have same start time)
- [ ] **Game status agreement** (Final, Postponed, etc.)
- [ ] **Team name consistency** (abbreviations match)

---

## Category 7: Time-Based & SLA Validations

### High Priority

#### 7.1 Pipeline Latency Tracking
**Measure end-to-end data flow speed**

**Config**: `validation/configs/performance/pipeline_latency.yaml`

**Metrics**:
- [ ] **Game end → BDL availability** (target: <30 minutes)
- [ ] **BDL → Analytics processed** (target: <15 minutes)
- [ ] **Analytics → ML features** (target: <10 minutes)
- [ ] **ML features → Predictions** (target: <5 minutes)
- [ ] **Total latency** (target: <60 minutes game end to predictions)

**Example Query**:
```sql
-- Calculate pipeline latency
WITH game_end_times AS (
  SELECT
    game_id,
    game_date,
    MAX(game_end_timestamp) as game_ended_at
  FROM nba_raw.nbac_schedule
  WHERE game_date = CURRENT_DATE()
    AND game_status_text = 'Final'
  GROUP BY game_id, game_date
),
analytics_times AS (
  SELECT
    game_id,
    MIN(created_at) as analytics_created_at
  FROM nba_analytics.player_game_summary
  WHERE game_date = CURRENT_DATE()
  GROUP BY game_id
)
SELECT
  g.game_id,
  g.game_ended_at,
  a.analytics_created_at,
  TIMESTAMP_DIFF(a.analytics_created_at, g.game_ended_at, MINUTE) as latency_minutes
FROM game_end_times g
LEFT JOIN analytics_times a ON g.game_id = a.game_id
ORDER BY latency_minutes DESC;
```

#### 7.2 SLA Compliance Tracking
**Define and track service level agreements**

**SLAs to track**:
- [ ] **Predictions available** (T-2 hours before game time)
- [ ] **Injury reports updated** (5 PM and 8 PM ET daily)
- [ ] **Grading completed** (within 12 hours of game end)
- [ ] **Uptime** (99.9% availability for critical services)

---

## Category 8: Business Logic Validations

### High Priority

#### 8.1 Betting Line Movement Validation
**Detect unusual or suspicious line movements**

**Validations**:
- [ ] **Sharp movement detection** (>2 point move in <1 hour)
- [ ] **Steam moves** (all bookmakers move simultaneously)
- [ ] **Reverse line movement** (line moves opposite of betting %age)
- [ ] **Injury-related moves** (correlation with injury news)

#### 8.2 Player Usage Pattern Analysis
**Early injury detection through usage anomalies**

**Validations**:
- [ ] **Minutes played variance** (detect load management)
- [ ] **Shot attempt variance** (detect usage changes)
- [ ] **DNP pattern detection** (rest days, injury management)
- [ ] **Back-to-back performance** (fatigue indicators)

---

## Category 9: Infrastructure Validations

### Medium Priority

#### 9.1 GCS File Integrity
**Validations**:
- [ ] **File size reasonableness** (not 0 bytes, not huge)
- [ ] **JSON structure valid** (parseable, not corrupted)
- [ ] **File naming conventions** (consistent patterns)
- [ ] **Orphaned files** (GCS files not in BigQuery)

#### 9.2 BigQuery Table Health
**Validations**:
- [ ] **Partition presence** (all dates have partitions)
- [ ] **Partition size** (reasonable row counts)
- [ ] **Table growth rate** (detect unexpected spikes)
- [ ] **Clustering effectiveness** (query performance over time)

#### 9.3 Firestore Consistency
**Validations**:
- [ ] **Stuck processors** (>30 min in 'running' state)
- [ ] **Phase completion freshness** (phase3/4/5 documents updated)
- [ ] **Write latency** (Firestore performance degradation)

---

## Category 10: Orchestration Validations

### High Priority

#### 10.1 Workflow Execution Patterns
**Validations**:
- [ ] **Workflow schedule adherence** (runs at expected times)
- [ ] **Workflow success rate** (>95% success expected)
- [ ] **Workflow duration** (detect slowdowns)
- [ ] **Workflow dependency resolution** (prerequisites met)

#### 10.2 Recovery Mechanism Effectiveness
**Validations**:
- [ ] **Morning recovery success rate** (catches missed games?)
- [ ] **Retry success rate** (retries fix transient failures?)
- [ ] **Manual intervention frequency** (how often needed?)

---

## Prioritization Framework

### Tier 1: Critical (Implement Next)
1. **Injury report validation** - Business critical, affects predictions
2. **ML feature quality** - Garbage in = garbage out
3. **System performance tracking** - Need to know which models work
4. **BDL vs NBA.com comparison** - Data quality foundation
5. **Pipeline latency tracking** - SLA compliance

### Tier 2: Important (Implement Soon)
6. **Gamebook processor validation** - R-009 monitoring
7. **Team analytics validation** - Completeness check
8. **Edge calculation validation** - Betting value measurement
9. **Props market comparison** - Market efficiency insights
10. **Confidence calibration** - Trust in predictions

### Tier 3: Nice to Have (Future)
11. **Play-by-play validation**
12. **Referee analytics**
13. **News pipeline validation**
14. **Model drift detection**
15. **Infrastructure health checks**

---

## Implementation Strategy

### Phase 1 (Week 1-2): Foundation
- Create configs for Tier 1 validators
- Implement critical validations
- Test with historical data

### Phase 2 (Week 3-4): Expansion
- Add Tier 2 validators
- Create cross-source comparison framework
- Implement automated reporting

### Phase 3 (Month 2): Advanced
- Time-based validations
- Business logic validations
- Model performance tracking

### Phase 4 (Month 3): Polish
- Infrastructure validations
- Orchestration monitoring
- Comprehensive dashboards

---

## Success Metrics

By end of Phase 4:
- ✅ 20+ validation configs created
- ✅ All critical data sources validated
- ✅ Cross-source discrepancies <1%
- ✅ Pipeline latency <60 minutes
- ✅ 99%+ data quality score
- ✅ Model performance tracked and reported

---

## Quick Wins (Can Do Now)

1. **Add injury report peak hour check** (2 hours)
   ```bash
   # Check 5 PM and 8 PM coverage
   bq query "SELECT report_hour, COUNT(*) FROM nba_raw.nbac_injury_report WHERE game_date = CURRENT_DATE() AND report_hour IN (17,20) GROUP BY report_hour"
   ```

2. **Check team totals vs player totals** (1 hour)
   ```sql
   -- See query in section 2.2
   ```

3. **Calculate pipeline latency for yesterday** (1 hour)
   ```sql
   -- See query in section 7.1
   ```

4. **Confidence calibration analysis** (2 hours)
   ```sql
   -- See query in section 5.3
   ```

5. **BDL vs NBA.com comparison** (2 hours)
   ```sql
   -- See query in section 6.1
   ```

---

**Document Version**: 1.0
**Created**: 2026-01-16
**Next Review**: After Phase 1 validators implemented
