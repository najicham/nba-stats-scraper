# MLB Pitcher Strikeouts - Quick Reference

## Timeline Overview

| Phase | Duration | Focus |
|-------|----------|-------|
| **0: Sport Abstraction** | Week 1-2 | Refactor 550 files to support multi-sport |
| **1: GCP Infrastructure** | Week 2 | Create MLB buckets, datasets, topics |
| **2: Scrapers** | Week 3-5 | 8 scrapers (Statcast, MLB API, Odds API) |
| **3: Raw Processors** | Week 5-6 | 5 processors for raw data |
| **4: Analytics** | Week 7-8 | pitcher_game_summary, team stats |
| **5: Feature Store** | Week 8-9 | 25-feature vector for predictions |
| **6: ML Training** | Week 9-10 | XGBoost model on 2+ seasons |
| **7: Predictions** | Week 10-11 | 4-system ensemble |
| **8: Deployment** | Week 11-12 | Testing, staging, production |

**Total: 14-20 weeks**

---

## Refactoring Scope at a Glance

```
Hardcoded References to Change:
├── nba-props-platform  → ${PROJECT_ID}     (193 files)
├── nba-scraped-data    → ${SPORT}-scraped-data   (82 files)
├── nba_raw             → ${SPORT}_raw      (242 files)
├── nba-phase1-*        → ${SPORT}-phase1-* (1 file, centralized)
└── nba_team_mapper     → SportTeamMapper   (20 files)

Total Effort: 50-65 hours
```

---

## Key Data Sources

| Source | What It Provides | Package |
|--------|------------------|---------|
| Baseball Savant | Pitch-by-pitch, Statcast | `pybaseball` |
| MLB Stats API | Schedule, rosters | Native HTTP |
| FanGraphs | K/9, K%, xFIP, WAR | `pybaseball` |
| Baseball Reference | Historical game logs | `pybaseball` |
| The Odds API | Pitcher strikeout lines | Already in codebase |

---

## 25 Features for Strikeout Prediction

```
Performance (0-4):     strikeouts_avg_last_5/10/season, std, innings
Pitcher (5-8):         fatigue, swinging_strike_rate, first_pitch_strike, velocity
Matchup (9-12):        opp_k_rate, opp_contact_rate, handedness, umpire_tendency
Environment (13-17):   ballpark_factor, is_home, rest, day_game, temperature
Arsenal (18-21):       fastball%, breaking%, offspeed%, spin_rate_percentile
Context (22-24):       expected_innings, bullpen_usage, game_importance
```

---

## First Steps

1. **Create sport_config.py**
   ```python
   SPORT = os.environ.get('SPORT', 'nba')
   RAW_DATASET = f"{SPORT}_raw"
   ```

2. **Update pubsub_topics.py**
   ```python
   def topic(phase: str) -> str:
       return f"{SPORT}-{phase}"
   ```

3. **Find-and-replace dataset names**
   ```bash
   # Example pattern
   sed -i 's/nba_raw/RAW_DATASET/g' file.py
   ```

---

## Key Decisions Made

- **Single repo** with sport parameter (not separate repos)
- **Shared base classes** (ScraperBase, ProcessorBase)
- **Separate GCP resources** (mlb-scraped-data, mlb_raw datasets)
- **Same 6-phase pipeline** (Scrape → Raw → Analytics → Precompute → Predict → Publish)
- **Same 4-model ensemble** (Moving Avg, Similarity, XGBoost, Ensemble)

---

## Links

- [Full Project Plan](./PROJECT-PLAN.md)
- [The Odds API MLB Docs](https://the-odds-api.com/sports/mlb-odds.html)
- [pybaseball GitHub](https://github.com/jldbc/pybaseball)
- [Baseball Savant](https://baseballsavant.mlb.com/)
