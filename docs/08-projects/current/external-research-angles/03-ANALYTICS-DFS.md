# Analytics Sites & DFS Community Research

## Summary

Research across DFS strategy sites, analytics platforms, NBA tracking data APIs, academic
papers, and betting analytics sources. Focused on identifying data sources and features
not currently in our 54-feature V12 set. Eight actionable angles identified, ranging from
free NBA.com tracking endpoints (touches, drives, catch-and-shoot) to referee O/U tendencies
and defense-vs-position matchup data. Several angles overlap with known dead ends (noted
below). The highest-value additions are tracking-based shot profile features and referee
pace data, both available via free APIs.

**Key findings:**
- NBA.com tracking endpoints (`nba_api` library) expose 12 tracking measure types we do not use (drives, touches, catch-and-shoot, pull-up, post touches, paint touches, speed/distance)
- Referee O/U tendencies are tracked by Covers.com and NBAstuffer with game-by-game data; our scraper pipeline for referee data (`nbac_referee_game_assignments`) is broken but fixable
- Defense-vs-position data is available from BettingPros (embedded JSON), FantasyPros, Dunkest, and nba_api (`leaguedashptdefend` endpoint)
- DFS ownership is a contrarian signal (high ownership = line inflation), but data access requires paid scrapers or manual collection
- Blowout probability / game script prediction is a well-studied angle with direct impact on starter minutes and UNDER bias in lopsided games
- Denver altitude effect is real but small and hard to isolate from other home-court factors
- Extended rest beyond B2B (3+ days) shows non-linear performance impact: 2 days rest is optimal, 3+ days shows slight decline (rhythm loss)

---

## Angles Found

### Angle 1: Player Tracking — Drives, Touches, and Shot Type Profiles
- **Source:** [nba_api LeagueDashPtStats endpoint](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/leaguedashptstats.md), [BoxScorePlayerTrackV3](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/boxscoreplayertrackv3.md), [NBA.com Tracking Stats](https://www.nba.com/stats)
- **Description:** NBA.com exposes 12 tracking measure types via `LeagueDashPtStats`: SpeedDistance, Rebounding, Possessions, CatchShoot, PullUpShot, Defense, Drives, Passing, ElbowTouch, PostTouch, PaintTouch, Efficiency. The `BoxScorePlayerTrackV3` endpoint provides per-game touches, distance, speed, and shooting breakdowns. The `nba_api` Python library (MIT license, free) wraps all of these. Shot type breakdowns (catch-and-shoot vs pull-up) are especially relevant: league-average C&S 3PT% is 36.4% vs pull-up 32.8%, and a player's C&S ratio reflects their offensive role stability and matchup sensitivity.
- **Claimed Edge:** Tracking data log-loss of 0.30 vs play-by-play log-loss of 0.40 (per "Beyond the Box Score" feature engineering article, Feb 2026). Pull-up vs drop coverage schemes create exploitable matchup signal.
- **Direction:** BOTH
- **Data Required:** `nba_api` Python library scraping NBA.com tracking endpoints. Per-game or rolling averages for: touches, drives, C&S FGA%, pull-up FGA%, paint touches, post touches, avg speed.
- **Have It?** NO — we have shot zone percentages (features 18-21: pct_paint, pct_mid_range, pct_three, pct_free_throw) but NOT tracking-based shot creation data (drives, touches, C&S ratio).
- **Dead End Overlap:** NONE. V13 shooting features (6 features: made/attempted/pct for 2PT and 3PT) were dead ends, but those are box-score shooting, not tracking-level shot creation. Tracking data is fundamentally different: it captures HOW shots are created (off dribble vs catch, distance to defender, paint touches), not just what was made.
- **Complexity:** MEDIUM — new scraper using `nba_api` library + feature engineering. No new paid API needed. Endpoint rate-limited by NBA.com (cloud providers sometimes blocked).
- **Specific features to build:**
  - `drives_per_game_last_5` — ball-handling role proxy, predicts usage stability
  - `catch_shoot_ratio_last_5` — C&S FGA / total FGA, measures role dependency on playmakers
  - `paint_touches_per_game` — inside scoring opportunity, correlates with FTA
  - `pull_up_fg_pct_last_10` — shot creation ability, higher = less matchup dependent
  - `touches_per_game_last_5` — overall involvement, proxy for offensive role

### Angle 2: Referee Over/Under Tendencies
- **Source:** [Covers.com NBA Referee Betting Stats 2025-26](https://www.covers.com/sport/basketball/nba/referees/statistics/2025-2026), [NBAstuffer Referee Stats](https://www.nbastuffer.com/2025-2026-nba-referee-stats/), [RefMetrics](https://www.refmetrics.com/nba/referee-assignments-today), [NBA Official Referee Assignments](https://official.nba.com/referee-assignments/)
- **Description:** Each NBA referee has measurably different foul rates, total points per game, and O/U tendencies. NBAstuffer tracks 130+ referees with game-by-game Excel data including total points per game, fouls per game, home/road foul differential. Covers.com provides referee-level ATS and O/U records. RefMetrics provides career profiles, workload trends, and foul-pattern analytics. Referee assignments are posted daily at 9:00 AM ET. The angle: certain referee crews consistently officiate higher-scoring or lower-scoring games, which shifts player scoring expectations by 1-3 points.
- **Claimed Edge:** Home team score increases by 1.1 points and visitor by 1.6 points with optimal rest + referee pairing (Wharton study). Referee O/U records vary significantly (some crews 60%+ OVER or UNDER across 30+ games).
- **Direction:** BOTH — high-foul refs favor OVER (more FTA = more points), low-foul refs favor UNDER
- **Data Required:** (1) Daily referee assignment scraper (NBA.com posts at 9 AM ET), (2) Historical referee stats (NBAstuffer Excel or Covers.com), (3) Join referee crew to game predictions before model run.
- **Have It?** NO — our `nbac_referee_game_assignments` scraper is broken (BQ table empty for 2025-26 season, noted in CLAUDE.md dead ends). The data source exists, the pipeline is broken.
- **Dead End Overlap:** "referee pace C10" is listed as dead end because `nbac_referee_game_assignments` table was empty. The dead end is the broken scraper, NOT the concept. Fixing the scraper would unlock this angle.
- **Complexity:** MEDIUM — fix existing broken scraper, build referee tendency lookup, add 1-2 features (referee_avg_total_points, referee_ou_lean). SportsDataIO API also has referee assignments in their Box Score endpoints as an alternative data source.

### Angle 3: Defense vs. Position Matchup Scoring
- **Source:** [BettingPros Defense vs Position](https://www.bettingpros.com/nba/defense-vs-position/), [Dunkest Defense vs Position 2025-26](https://www.dunkest.com/en/nba/stats/teams/defense-vs-position/regular-season/2025-2026), [FantasyPros DvP](https://www.fantasypros.com/daily-fantasy/nba/fanduel-defense-vs-position.php), [nba_api LeagueDashPtDefend](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/leaguedashptdefend.md)
- **Description:** Defense-vs-Position (DvP) data shows how many points/rebounds/assists each team allows to each position (PG/SG/SF/PF/C). BettingPros embeds structured JSON (`bpDefenseVsPositionStats`) with per-team, per-position scoring allowed. The `nba_api` `leaguedashptdefend` endpoint provides defender-level tracking: D_FGM, D_FGA, D_FG_PCT, NORMAL_FG_PCT, PCT_PLUSMINUS by DefenseCategory (Overall, 3PT, 2PT, Less Than 6Ft, Greater Than 15Ft). This is more granular than our current `opponent_def_rating` (feature 13) which is team-level only.
- **Claimed Edge:** DFS community widely uses DvP as a primary matchup filter. Teams allowing significantly more points to specific positions (e.g., team allows 28 PPG to PGs vs league average 22) create 3-6 point scoring differentials.
- **Direction:** BOTH — favorable DvP = OVER lean, unfavorable DvP = UNDER lean
- **Data Required:** Player position mapping + per-opponent DvP scoring matrix. Two options: (1) scrape BettingPros/Dunkest, (2) use `nba_api` `leaguedashptdefend` endpoint (free, official NBA data).
- **Have It?** PARTIAL — we have `opponent_def_rating` (feature 13) and `shot_zone_mismatch_score` (feature 7), but these are team-level. We do NOT have position-specific defensive weakness data.
- **Dead End Overlap:** NONE. V17 "opponent risk" features (blowout_minutes_risk, minutes_volatility, opponent_pace_mismatch) were dead ends, but those measured opportunity risk, not positional defensive weakness.
- **Complexity:** MEDIUM — requires player position mapping (available from nba_api) + DvP lookup table updated daily. Feature: `dvp_points_allowed_vs_position` (normalized 0-1 scale, opponent's rank in points allowed to player's position).

### Angle 4: DFS Ownership as Line Inflation Proxy
- **Source:** [Fantasy Alarm DFS Ownership](https://www.fantasyalarm.com/nba/dfs-ownership-percentages), [Stokastic Ownership Projections](https://www.stokastic.com/nba/nba-dfs-projections-draftkings-fanduel), [LineStarApp Ownership](https://www.linestarapp.com/Ownership/Sport/NBA/Site/DraftKings), [FantasyTeamAdvice Ownership](https://fantasyteamadvice.com/dfs/nba/ownership)
- **Description:** High DFS ownership ("chalk") indicates the market consensus expects a player to outperform. DFS community theory: when a player is 30%+ owned, sportsbooks have likely already adjusted the prop line upward, creating UNDER value. The correlation: high DFS ownership = narrative-driven demand = inflated lines. Conversely, low ownership = overlooked = potential OVER value. Ownership projections update in real-time as injury news breaks and lineups are confirmed. Multiple platforms offer projected ownership for DraftKings and FanDuel slates.
- **Claimed Edge:** DFS contrarian strategies are well-documented. High-chalk players underperform GPP expectations. The crossover to props: if DFS ownership > 25%, the line is likely adjusted upward by 1-2 points, creating UNDER value.
- **Direction:** UNDER (for high ownership), OVER (for low ownership)
- **Data Required:** DFS ownership projections scraped from Fantasy Alarm, Stokastic, or LineStarApp daily before model run. Need: player name, projected ownership %, platform (DK/FD).
- **Have It?** NO
- **Dead End Overlap:** NONE — this is a completely new data dimension (market sentiment proxy)
- **Complexity:** HIGH — requires new scraper for DFS ownership data, which is typically behind auth walls or dynamically loaded. Some sites (FantasyTeamAdvice) offer free downloads. Data is only available ~2-4 hours before lock, which may be too late for our 6 AM ET pipeline.
- **Viability concern:** Timing mismatch is significant. DFS ownership projections are most accurate close to game time, but our pipeline runs early morning. Early ownership projections may not reflect late injury news that drives the biggest swings. Could work as a supplemental signal rather than a core feature.

### Angle 5: Blowout Probability and Game Script Impact
- **Source:** [LSports Blowout Vulnerability Analysis](https://www.lsports.eu/blog/the-30-point-problem-how-basketball-blowouts-expose-trading-vulnerabilities/), [JTCies Garbage Time Analysis](https://jtcies.com/2020/03/when-does-garbage-time-start/), [Inpredictable Game Win Probability](https://www.inpredictable.com/2015/02/how-nba-games-are-won.html), [Cleaning the Glass Garbage Time Guide](https://cleaningtheglass.com/stats/guide/garbage_time)
- **Description:** Games with large point spreads (15+) have higher blowout probability, which causes starters to sit the entire 4th quarter. This directly impacts points props. Garbage time definition from the analytics community: 4th quarter, score differential >= 25 (minutes 12-9), >= 20 (minutes 9-6), >= 10 (remainder), with 2 or fewer starters on floor. A starter expected to play 36 minutes might only get 28 in a blowout, reducing scoring output by 20%+. Research shows walking/standing increases from 69.1% in Q1 to 73% in Q4 at altitude (Denver study), compounding the effect.
- **Claimed Edge:** Spread >= 10 games have 40%+ chance of garbage time in Q4. Starters lose 5-8 minutes in blowouts. Player prop models that don't account for this systematically overpredict star scoring in mismatched games.
- **Direction:** UNDER (for starters in projected blowouts), potentially OVER for bench players who get extended minutes
- **Data Required:** We already have `spread_magnitude` (feature 41) and `implied_team_total` (feature 42). The gap is translating spread into blowout probability and expected minutes reduction. Could derive: `blowout_probability` = f(spread, team variance, historical blowout rate), `expected_minutes_adjustment` = f(blowout_prob, player_tier).
- **Have It?** PARTIAL — we have spread and implied team total but do NOT derive blowout probability or expected minutes reduction from them.
- **Dead End Overlap:** `blowout_recovery` signal (50% HR, disabled Session 349) and V17 `blowout_minutes_risk` feature (<1% importance, dead end). However, those measured "recovery after blowout" and "historical blowout risk for team", not "pre-game blowout probability for THIS game based on spread". The pre-game angle (spread-derived blowout probability) has not been tried.
- **Complexity:** LOW — derived feature from existing data (spread_magnitude). No new scraper needed. Feature: `blowout_prob` = sigmoid(spread_magnitude, center=10, scale=3). Could also use as an UNDER signal rather than a model feature.

### Angle 6: Extended Rest Non-Linear Effects (3+ Days)
- **Source:** [NBAstuffer Rest Day Stats](https://www.nbastuffer.com/nba-stats/restdays/), [Wharton Rest and Home Court Study](https://faculty.wharton.upenn.edu/wp-content/uploads/2012/04/Nba.pdf), [HeatCheck HQ B2B Analysis](https://heatcheckhq.io/blog/nba-back-to-back-rest-analysis), [CMU Load Management Impact Study](https://www.stat.cmu.edu/capstoneresearch/460files_s25/team15.pdf)
- **Description:** Research shows a non-linear relationship between rest and performance. The sweet spot is 2 days rest (performance metrics return to baseline or slightly above). At 3+ days rest, scoring actually decreases — "shooters are like the rest of us, a little slow getting back after a long weekend." Additionally, schedule density features ("3 games in 4 nights", "5 games in 7 days") show statistically significant negative correlation with eFG% and defensive rating, particularly among high-usage veterans. The CMU study found rest days have low feature importance in linear models but meaningful non-linear effects.
- **Claimed Edge:** 2 days rest = +1.1 pts home, +1.6 pts visitor. 3+ days = slight decline from rhythm loss. B2B impact = -1.5 to -2.5 points per 100 possessions.
- **Direction:** BOTH — 2-day rest OVER, 3+ day rest UNDER (rhythm loss), schedule density UNDER
- **Data Required:** We have `days_rest` (feature 39), `back_to_back` (feature 16), `games_in_last_7_days` (feature 4). Gap: non-linear encoding. A binary `extended_rest_rhythm_loss` flag (days_rest >= 4) or polynomial feature could capture the non-linear effect.
- **Have It?** PARTIAL — we have the raw data but encode it linearly. We already have `extended_rest_under` signal (61.8% HR) and `rest_advantage_2d` signal (disabled for season). Our calendar regime analysis (Session 395) found B2B is actually +4-7pp BETTER than rested during certain windows.
- **Dead End Overlap:** `extended_rest_under` signal exists at 61.8% HR (PRODUCTION). `rest_advantage_2d` disabled (re-enable October). `extended rest 4+d OVER block` was researched Session 372 but used wrong feature column. The non-linear encoding of rest as a MODEL FEATURE (not signal) has not been tried.
- **Complexity:** LOW — derived feature from existing `days_rest`. Feature: `rest_squared` = days_rest^2 or categorical buckets [0=B2B, 1=1day, 2=2day_optimal, 3=3day_slight_decline, 4=4plus_rhythm_loss].

### Angle 7: Coaching Rotation Tightness / Bench Usage Stability
- **Source:** [RotoWire NBA Rotations](https://www.rotowire.com/basketball/rotations.php), [NBARotations.info](https://nbarotations.info/), [RotoWire Minutes Report](https://www.rotowire.com/basketball/minutes.php), [NBA.com Lineups Advanced](https://www.nba.com/stats/lineups/advanced), [CoreSportsBetting Rotation Stability](https://www.coresportsbetting.com/how-nba-rotation-stability-affects-point-spread-betting/)
- **Description:** Rotation stability — how consistently a coach uses the same 8-9 man rotation — directly impacts minutes predictability, which is the single biggest driver of player scoring props. A tight 8-man rotation means starter minutes are predictable (34-36 per game). A loose 10-11 man rotation introduces variance (28-36 per game). Coaches who tighten rotations mid-season (e.g., playoff push) create systematic OVER value for starters as their minutes floor rises. Minutes entropy (how evenly distributed minutes are across 12+ players) is a measurable team-level feature available from NBA.com lineups data.
- **Claimed Edge:** "If the top eight or nine players consistently log similar minutes each night, stability is present." Minutes consistency has a direct mechanical relationship with scoring output — more predictable minutes = more predictable points = better model accuracy.
- **Direction:** BOTH — tight rotation for starters = OVER (more minutes), loose rotation = UNDER (minutes variance)
- **Data Required:** Team rotation data from NBA.com Lineups Advanced endpoint or RotoWire. Compute: minutes entropy per team (Shannon entropy of minutes distribution), rotation_size (count of players averaging 10+ minutes), starter_minutes_cv (coefficient of variation for starter minutes over last 5 games).
- **Have It?** NO — we have individual player minutes data (features 31-32: `minutes_avg_last_10`, `ppm_avg_last_10`) and `minutes_change` (feature 12), but NOT team-level rotation stability metrics.
- **Dead End Overlap:** NONE — rotation stability is a team-level context feature, not an individual player feature like our existing minutes data.
- **Complexity:** MEDIUM — requires computing team rotation metrics from existing NBA.com data. Could use `nba_api` lineups endpoint. Feature: `team_rotation_tightness` (8-man=tight=1.0, 12-man=loose=0.0, normalized).

### Angle 8: Closest Defender Distance and Defensive Scheme
- **Source:** [NBA.com Teams Opponent Shooting Closest Defender](https://www.nba.com/stats/teams/opponent-shots-closest-defender), [nba_api LeagueDashPtDefend](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/leaguedashptdefend.md), [Players Shooting Closest Defender](https://www.nba.com/stats/players/shots-closest-defender)
- **Description:** NBA.com tracks shooting efficiency by closest defender distance: 0-2 ft (Very Tight), 2-4 ft (Tight), 4-6 ft (Open), 6+ ft (Wide Open). Each team's defensive scheme creates different shot quality profiles. A team that plays aggressive defense creates more "Very Tight" contests but fouls more (favoring FTA/OVER). A team that plays drop coverage allows more "Open" attempts. The `leaguedashptdefend` endpoint returns per-defender D_FGM, D_FGA, D_FG_PCT, NORMAL_FG_PCT, PCT_PLUSMINUS by category (Overall, 3PT, 2PT, Less Than 6Ft, Greater Than 15Ft). This is the most granular defensive matchup data available.
- **Claimed Edge:** "Quantified Shot Quality (qSQ) calculates likelihood based on shooter/defender positioning" — tracking data at this level improves prediction log-loss from 0.40 to 0.30 vs play-by-play alone. Open 3PT% (6+ ft defender) differs from contested 3PT% (0-2 ft) by 15-20 percentage points league-wide.
- **Direction:** BOTH — open-shot-creating defenses = OVER for shooters, tight-contest defenses = UNDER for volume scorers
- **Data Required:** `nba_api` `leaguedashptdefend` endpoint (free). Per-opponent: pct of shots that are Wide Open, Open, Tight, Very Tight. Per-player: their FG% in each defender distance bucket. Feature: `matchup_shot_quality_score` = player's expected efficiency given opponent's defender distance profile.
- **Have It?** NO — our `shot_zone_mismatch_score` (feature 7) uses shot zone distributions (paint/mid/3PT/FT) but does NOT incorporate defender distance or contest frequency.
- **Dead End Overlap:** NONE. This is fundamentally different from our shot zone features. `shot_zone_mismatch_score` measures WHERE a player shoots vs WHERE the opponent allows shots. This angle measures HOW CONTESTED those shots will be.
- **Complexity:** HIGH — requires new scraper for defender distance data, player-level matchup matrix computation, and feature engineering. Defender distance profiles change throughout the season and by lineup. The `leaguedashptdefend` endpoint is free but rate-limited.

---

## Data Source Accessibility Summary

| Source | Cost | Access Method | Rate Limits | Data Freshness |
|--------|------|---------------|-------------|----------------|
| nba_api (tracking) | Free | Python library | NBA.com blocks some cloud IPs | Same-day after game |
| nba_api (defense) | Free | Python library | Same as above | Same-day |
| BettingPros DvP | Free | Embedded JSON scrape | Unknown | Daily |
| Covers.com Refs | Free | Web scrape | Unknown | Same-day |
| NBAstuffer Refs | Paid Excel | Manual download or API | N/A | 2-4 hours post-game |
| RefMetrics | Free | Web scrape | Unknown | Real-time assignments |
| NBA Official Assignments | Free | Scrape official.nba.com | Unknown | 9 AM ET daily |
| DFS Ownership | Free-Paid | Various scrapers | Auth walls common | 2-4 hours pre-lock |
| SportsDataIO Refs | Paid API | REST API | Subscription-based | Real-time |
| RotoWire Rotations | Paid | Subscription | N/A | Daily |

## Priority Ranking

Based on expected edge, data accessibility, and implementation complexity:

| Rank | Angle | Priority | Rationale |
|------|-------|----------|-----------|
| 1 | Referee O/U Tendencies | HIGH | Fix broken scraper, Covers.com data is free, 1-3 point scoring differential per crew |
| 2 | Tracking Shot Profiles | HIGH | Free nba_api, captures role stability and shot creation, fills our biggest feature gap |
| 3 | Defense vs Position | MEDIUM | Free nba_api endpoint, more granular than team-level opponent_def_rating |
| 4 | Blowout Probability | MEDIUM-LOW | Derived from existing features, no new scraper, but overlaps with spread_magnitude which model already sees |
| 5 | Rotation Tightness | MEDIUM | Available from NBA.com, new dimension (team-level), but requires aggregation pipeline |
| 6 | Extended Rest Non-Linear | LOW | Already have signals for this; non-linear encoding is incremental |
| 7 | Closest Defender Distance | MEDIUM | Rich data but HIGH complexity; long-term project |
| 8 | DFS Ownership | LOW | Timing mismatch with pipeline, auth walls, conceptually interesting but impractical |

## Implementation Notes

**Angles 1 + 3 + 8 share infrastructure:** All use `nba_api` Python library and NBA.com endpoints. A single tracking data scraper could pull all three categories (player tracking stats, defense-vs-position, closest defender) in one pipeline phase. The main constraint is NBA.com rate limiting and IP blocking on cloud providers.

**Angle 2 (referee) is most actionable short-term:** The `nbac_referee_game_assignments` scraper exists but is broken. Fixing it + adding a Covers.com scraper for historical O/U records would provide immediate signal. Referee assignments at 9 AM ET fits our pipeline timing perfectly.

**Angle 5 (blowout) is a quick win:** Pure derived feature from `spread_magnitude`, no new data needed. Could implement as signal first (like `extended_rest_under`), then promote to model feature if signal validates.

**All tracking-based angles (1, 3, 7, 8) have a shared risk:** NBA.com blocks cloud provider IPs. Our scrapers run on Cloud Run/Cloud Functions. Solutions: (1) use a residential proxy, (2) run tracking scrapers from a non-cloud VM, (3) use SportsDataIO paid API as fallback.
