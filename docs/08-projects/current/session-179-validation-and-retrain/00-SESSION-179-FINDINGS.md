# Session 179: Data Validation, Odds Pipeline, and Retrain Experiments

**Date:** 2026-02-09
**Focus:** Weekly source/Phase 2 data validation, odds pipeline investigation, clean model retrain

---

## 1. Source Data & Phase 2 Validation (Feb 3-9)

### Healthy Sources

| Source | Daily Rows | Coverage | Notes |
|--------|-----------|----------|-------|
| NBA.com Gamebook (`nbac_gamebook_player_stats`) | 135-350 | All 45 final games | Primary stats source |
| NBA.com Boxscore (`nbac_boxscore_traditional`) | 96-217 | All games | Healthy |
| NBA.com Schedule (`nbac_schedule`) | Matches game count | 55 games total | No stale statuses |
| NBA.com Injury Report (`nbac_injury_report`) | 4K-6K | 26-29 teams/day | Very consistent |
| BDL Injuries (`bdl_injuries`) | 10K-12K | Daily | Healthy fallback |
| Odds API Game Lines (`odds_api_game_lines`) | 64-400 | 2 sportsbooks | Consistent |
| BettingPros Player Props (`bettingpros_player_points_props`) | 185K-486K | 19 sportsbooks, 62-174 players | **Workhorse source** |
| Phase 2 Processing | All `status=success` | Zero errors | Clean all week |
| Phase 3 Analytics | Player + team summaries correct | All 6 completed days | Downstream healthy |
| Phase 4 Feature Store | 82-87 avg quality | ~40% clean players | Zero tolerance working |

### Issues Found

| # | Source | Severity | Finding | Impact |
|---|--------|----------|---------|--------|
| 1 | BDL Boxscores (`bdl_player_boxscores`) | Medium | No data since Feb 7 | Secondary source, no prediction impact |
| 2 | Play-by-Play (`nbac_play_by_play`) | Low | Zero rows entire season; Big Data Ball (`bdb_pbp_scraper`) is primary PBP source | None — BDB is healthy |
| 3 | Odds API Player Props | Low | Feb 7 anomaly (23 rows vs 600-1200). Only 2 sportsbooks | BettingPros compensated |
| 4 | Gamebook PDF scraper | Low | Errors for games not yet completed (missing `game_code`) | Expected behavior — works for finished games |

---

## 2. Odds & Props Pipeline Deep Dive

### BettingPros vs Odds API Comparison

| Factor | Odds API | BettingPros | Winner |
|--------|----------|-------------|--------|
| Sportsbooks | 2 (DK, FD) | 19 | **BP** |
| Players/day | 12-132 | 62-174 | **BP** |
| Freshness (latest timestamp) | ~4 PM UTC | ~4 AM UTC next day | **BP** |
| Reliability (Feb 7 outage) | 12 players | 174 players | **BP** |
| DK line accuracy | Direct from API | 83.8% exact match with DK | Tie |
| Consensus vs DK diff | — | 0.16 pts avg, no bias | BP consensus reliable |
| Snapshot timestamps | Per-line timestamps | Final closing line on backfill | **OA** |

**Key insight:** Odds API's main advantage is per-line snapshot timestamps, useful for knowing when a line was released. BettingPros provides the closing/current line but doesn't track when specific sportsbooks first posted.

### Root Cause: Only 2 Odds API Sportsbooks

Hardcoded default in `scrapers/oddsapi/oddsa_player_props.py` and `oddsa_game_lines.py`:
```python
self.opts["bookmakers"] = "draftkings,fanduel"  # Was the filter
```

The Odds API `bookmakers` parameter is a whitelist — we were telling it to only return DK and FD.

### BettingPros Scraping Gap

- Lines first appear at **~2:00 AM ET** in BigQuery
- BettingPros workflow `business_hours.start` was **8:00 AM ET**
- 6-hour gap where lines exist but aren't being scraped

### Changes Made

1. **BettingPros earlier scraping:** `config/workflows.yaml` — changed `business_hours.start` from `8` to `5` (5 AM ET)
2. **Odds API expanded sportsbooks:** Both scraper files — changed default from `"draftkings,fanduel"` to `"draftkings,fanduel,betmgm,pointsbetus,williamhill_us,betrivers"` (6 books)
3. **README updated** to reflect new defaults

---

## 3. Model Retrain Experiments

### Background: Data Leakage in Session 177 Challengers

| Model | Training | Eval | Overlap? | Reported HR 3+ | Real Status |
|-------|----------|------|----------|----------------|-------------|
| `_train1102_0108` | Nov 2 - Jan 8 | Jan 9 - Feb 8 | **No** | 87.0% (n=131) | Clean — but 73/131 edge 3+ picks from Jan 12 alone |
| `_train1102_0208` | Nov 2 - Feb 8 | Jan 9 - Jan 31 | **31 days** | 91.8% (n=159) | **Contaminated** |
| `_train1102_0208_tuned` | Nov 2 - Feb 8 | Jan 9 - Jan 31 | **31 days** | 93.0% (n=157) | **Contaminated** |

The 91.8% and 93.0% numbers are invalid — models tested on training data. Session 176's date overlap guard now prevents this.

### Clean Experiment: Extended Training + Tuned Hyperparams

**V9_CLEAN_TUNED_FEB** — Train: Nov 2 - Jan 31, Eval: Feb 1-8, `--tune` flag

| Metric | Result | Baseline | |
|--------|--------|----------|---|
| MAE | 4.98 | 5.14 | Better |
| Overall HR | 53.7% | 54.5% | Similar |
| Edge 3+ HR | 0.0% (n=4) | 63.7% | **Problem** |
| Vegas bias | -0.09 | — | Excellent |

Grid search selected depth=5, l2=3.0, lr=0.03 — too conservative. Model tracks Vegas perfectly but generates almost no actionable picks.

### Clean Experiment: Extended Training + Default Hyperparams

**V9_CLEAN_DEFAULT_FEB** — Train: Nov 2 - Jan 31, Eval: Feb 1-8, default params

| Metric | Result | Baseline | |
|--------|--------|----------|---|
| MAE | 4.95 | 5.14 | Better |
| Overall HR | **60.0%** | 54.5% | **Much better** |
| Edge 3+ HR | 33.3% (n=6) | 63.7% | Low sample |
| Vegas bias | -0.03 | — | Near perfect |

Better than tuned version but same core problem: only 6 edge 3+ picks out of 269.

### The Retrain Paradox

**More training data → closer to Vegas → fewer actionable picks**

- Production model (trained Jan 8) diverges naturally from Feb Vegas lines → creates edge
- Retrained model (trained Jan 31) tracks Feb Vegas closely → almost no edge
- The "staleness" of the production model is actually what creates betting opportunities
- Retrained models are more accurate (lower MAE, higher overall HR) but less profitable

### Strategic Implications

1. **Model staleness creates edge** — counterintuitive but the data confirms it
2. **The tuned hyperparams (depth=5) make things worse** — too conservative for our use case
3. **Default params (depth=6) are better** — more aggressive, more divergence from Vegas
4. **The `_train1102_0108` challenger** (same dates as prod, better feature quality) may be the best path — it shows 75.9% edge 3+ on clean holdout (excluding Jan 12 outlier)
5. **Edge threshold may need adjustment** — if retrained models are more accurate overall (60% HR) but at lower edge, maybe edge 2+ or 1.5+ is profitable with updated models

---

## 4. Files Changed

| File | Change |
|------|--------|
| `config/workflows.yaml` | BettingPros `business_hours.start`: 8 → 5 |
| `scrapers/oddsapi/oddsa_player_props.py` | Bookmakers: `draftkings,fanduel` → 6 books |
| `scrapers/oddsapi/oddsa_game_lines.py` | Same bookmaker expansion |
| `scrapers/oddsapi/README.md` | Updated default docs |

---

## 5. Next Steps

- [ ] Deploy scraper changes (push to main triggers auto-deploy)
- [ ] Monitor Odds API for the new sportsbooks (check if betmgm/pointsbetus/etc return data)
- [ ] Monitor BettingPros earlier scraping (verify 5 AM ET runs start)
- [ ] Investigate `_train1102_0108` challenger further — best candidate with clean data
- [ ] Consider edge threshold analysis: is edge 1.5+ or 2+ profitable with retrained models?
- [ ] Investigate BDL boxscore drop-off (secondary priority)
