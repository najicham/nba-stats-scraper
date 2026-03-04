# Market-Based Angles Research

## Summary

Research into market microstructure, line movement patterns, and cross-book dynamics for NBA player props. The prop market is structurally less efficient than sides/totals because: (1) sportsbooks cannot allocate equal resources to pricing hundreds of individual markets, (2) there is no single sharp book for props the way Pinnacle dominates sides, (3) line movement reaction windows have compressed from 60 seconds to 15-30 seconds, making speed-to-information critical. Our existing infrastructure (Odds API multi-book snapshots, prop_line_delta, multi_book_line_std) already captures some market signal, but we are missing opening-line snapshots, CLV tracking, public betting percentages, and book-specific line origination timing.

Key takeaway: The most actionable angles are (1) CLV tracking via opening/closing line snapshots from Odds API historical endpoint (data available, not yet captured), (2) book-speed divergence using our existing multi-book data, and (3) mean-vs-median exploitation for skewed stat distributions.

---

## Angles Found

### Angle: Closing Line Value (CLV) Tracking
- **Source:** [Pinnacle — Why Betting Early Can Be More Profitable](https://www.pinnacle.com/betting-resources/en/educational/why-betting-early-can-be-more-profitable-nba-opening-vs-closing-line-odds), [Sharp Football Analysis — CLV Guide](https://www.sharpfootballanalysis.com/sportsbook/clv-betting/), [BettorEdge — CLV Explained](https://www.bettoredge.com/post/what-is-closing-line-value-in-sports-betting)
- **Description:** CLV measures the difference between the line at which you would bet and the closing line (final line before tip-off). Pinnacle's 2024-25 NBA data showed approximately 1.5% edge from wagering at opening lines vs closing. Professional bettors consider CLV the single best predictor of long-term profitability — a 2-5% edge over closing lines correlates with 15-25% annual ROI improvement. Consistently beating closing lines over hundreds of bets is the strongest signal of a profitable model, more predictive than raw win rate.
- **Claimed Edge:** 1.5% edge (opening vs closing), 2-5% CLV = 15-25% ROI improvement
- **Direction:** BOTH
- **Data Required:** Opening line snapshot (early morning, ~10 AM ET) and closing line snapshot (30 min before tip-off) for each player prop. The Odds API historical endpoint provides snapshots at 5-minute intervals — we could capture 2 snapshots per game day: opening (~4 AM UTC / ~11 PM ET prior day) and closing (~23:00 UTC / 6 PM ET game day).
- **Have It?** PARTIAL — We have Odds API access and the historical endpoint scraper (`oddsa_player_props_his.py`), but we do NOT currently capture systematic opening-line snapshots. We only store a single snapshot used for feature computation. Our `prop_line_delta` compares current game's line to previous game's line (different concept — game-over-game, not intra-day).
- **Dead End Overlap:** NONE — This is fundamentally different from prop_line_drop_over (which tracked game-over-game direction, not CLV).
- **Complexity:** MEDIUM — Requires adding a scheduled morning scrape (opening snapshot) and a pre-tipoff scrape (closing snapshot), then computing CLV = opening_line - closing_line per player. Store in supplemental data. No new scraper needed, just new scheduling of existing scraper.

### Angle: Soft-Book Line Lag (Book-Speed Divergence)
- **Source:** [Outlier — Soft vs Sharp Books](https://help.outlier.bet/en/articles/9922960-how-sportsbooks-set-odds-soft-vs-sharp-books), [PickTheOdds — Sharp Sportsbooks](https://picktheodds.app/en/blog/sharp-sportsbooks-what-they-are-and-how-to-use-them-to-find-edges), [Pikkit — Sportsbook Sharpness Rankings](https://www.pikkit.com/blog/which-sportsbooks-are-sharp)
- **Description:** Sharp books (FanDuel for NBA props, Pinnacle for sides) adjust lines quickly after sharp action, while soft/retail books (Caesars via Kambi, BetMGM) lag behind. When a sharp book moves a line and a soft book has not yet adjusted, the soft book's line represents stale value. Pikkit's sharpness rankings for NBA props: DraftKings (1.046), FanDuel (1.007), Caesars (0.995), Kambi (0.627 — major outlier). The gap between the sharpest book's line and the slowest book's line on the same player is a directional signal. This is different from our `multi_book_line_std` (which measures overall disagreement without direction) — this measures directional deviation FROM the sharp consensus.
- **Claimed Edge:** Line shopping across books adds "5-10% to your edge" per research-backed NBA strategy guides.
- **Direction:** BOTH
- **Data Required:** Per-book line data (which we already collect from Odds API with book identifiers). Need to: (1) classify books by sharpness tier (FanDuel/DK = sharp, Kambi/BetRivers = soft), (2) compute directional deviation: soft_book_line - sharp_consensus. Positive deviation on OVER = soft book is slower to move up = OVER value at soft book. Can also detect WHEN books converge as a confirmation signal.
- **Have It?** PARTIAL — We have per-book lines from Odds API (multiple bookmakers per player per snapshot). We compute `multi_book_line_std` but NOT directional deviation from sharp consensus. We already exclude Bovada (73.6% outlier rate). Adding a "sharp consensus" vs "soft outlier" metric is a supplemental query change.
- **Dead End Overlap:** NONE — This is directional, not just variance. Book disagreement (multi_book_line_std) captures magnitude; this captures direction relative to a benchmark.
- **Complexity:** LOW — Use existing per-book data. Define sharp tier (FanDuel, DraftKings) as benchmark. Compute signed deviation for each soft book. Could become a signal (`soft_book_lag_over` / `soft_book_lag_under`) without any new scraper.

### Angle: Reverse Line Movement (RLM) on Props
- **Source:** [Pinnacle Odds Dropper — Reverse Line Movement](https://www.pinnacleoddsdropper.com/blog/reverse-line-movement), [FantasyLife — What Is RLM](https://www.fantasylife.com/articles/betting/what-is-reverse-line-movement), [SportsBettingDime — NBA Public Betting Trends](https://www.sportsbettingdime.com/nba/public-betting-trends/)
- **Description:** RLM occurs when the line moves opposite to public betting percentages — e.g., 75% of bets on OVER but the line drops. This signals sharp money on the UNDER side, as books move lines to balance dollar exposure, not ticket count. For props: if public heavily bets OVER on a star player's points but the line falls from 25.5 to 24.5, sharps are pounding UNDER with larger individual wagers. Contrarian bettors who follow RLM consider it their "bread and butter." Key detection: compare ticket % (many small bets) vs money % (fewer large bets). When these diverge, sharp money is present.
- **Claimed Edge:** Not quantified in sources, but described as one of the most reliable sharp money indicators. Strongest when combined with timing (late RLM > early RLM) and magnitude (2+ point move against 70%+ public side).
- **Direction:** BOTH (bet WITH the line move, against public)
- **Data Required:** Public betting percentages (ticket splits and/or money splits) per player prop. Sources: Action Network PRO ($), DraftKings "Most Bet" data (free, updates every 5 min), TheSpread.com (free for game-level), Outlier.bet (props-level public data). Then combine with our existing `prop_line_delta` to detect divergence.
- **Have It?** NO — We do not have public betting percentages for player props. Action Network provides this behind a paywall. DraftKings Network publishes "most bet props" which is a partial proxy. This would require either a new scraper (DK Most Bet Props) or API subscription (Action Network).
- **Dead End Overlap:** NONE — Entirely new data dimension. Our prop_line_delta captures line direction but NOT whether it moved against public consensus.
- **Complexity:** HIGH — Requires new data source. Options: (A) Scrape DraftKings Network "most bet" page daily — free but incomplete, (B) Action Network subscription + scraper — comprehensive but costly, (C) Proxy via line movement direction + book count: if 8/10 books move one way and 2 lag, infer those 2 have the public money. Option C is a rough proxy implementable with existing data.

### Angle: Steam Move Detection (Multi-Book Rapid Convergence)
- **Source:** [Sports Insights — Steam Moves](https://www.sportsinsights.com/betting-systems/steam-moves/), [SportBot AI — Understanding Steam Moves](https://www.sportbotai.com/blog/understanding-steam-moves-betting-1770177744134), [Sports Insights — How to Win with Steam Moves](https://www.sportsinsights.com/how-to-win-with-steam-moves/)
- **Description:** Steam moves are sudden, uniform line shifts across all sportsbooks within minutes, triggered by $25K-$100K coordinated wagers from syndicates. For props: when 5+ books simultaneously move a player's points line in the same direction within a short window, it signals sharp syndicate action. Key insight from Sports Insights: some sharps place initial bets to MOVE the line, then bet $150K+ on the OTHER side at the adjusted line — making "false steam" detection critical. Late steam (within 1 hour of tip-off) is more reliable than early steam, because books raise limits close to game time and sharp money flows in.
- **Claimed Edge:** Sports Insights notes "blindly following every steam move caused a lot of players to go broke" — must filter false steam. True steam (verified by late timing + multiple sharp books moving) is profitable but requires distinguishing from injury-driven moves.
- **Direction:** BOTH (follow the steam direction)
- **Data Required:** Multiple intra-day line snapshots (minimum 3-4 per game day) to detect rapid multi-book convergence. With 2 snapshots (opening + closing), we can detect total movement but not SPEED. Ideal: snapshot at open, noon ET, 5 PM ET, and 30 min pre-tip. The Odds API historical endpoint supports this at 5-min intervals but API cost scales linearly.
- **Have It?** NO — We capture a single snapshot per game. Detecting steam requires temporal resolution (multiple snapshots). Our existing `prop_line_delta` is game-over-game, not intra-day.
- **Dead End Overlap:** NONE
- **Complexity:** HIGH — Requires 3-4 daily snapshots per game from Odds API (significant API cost increase), temporal storage schema, and convergence detection logic. Could start with just 2 snapshots (opening + closing) as a cheaper proxy — large CLV = possible steam move.

### Angle: Mean-vs-Median Skew Exploitation
- **Source:** [Unabated — Profitable Prop Betting in 3 Steps](https://unabated.com/articles/profitable-prop-betting-in-3-easy-steps), [Unabated — Fine Tune Your NBA Prop Strategy](https://unabated.com/articles/fine-tune-your-nba-prop-betting-strategy-using-unabated-nba)
- **Description:** Sportsbooks set prop lines at the MEDIAN (50th percentile of outcomes), not the MEAN (average). For right-skewed distributions (where floor is 0 but ceiling is unbounded), the mean exceeds the median. This means OVER has a higher payout when it hits but wins less than 50% of the time. Conversely, UNDER on skewed stats wins more often but pays less. The key insight: players with highly volatile, right-skewed scoring distributions (role players, streaky shooters) have a larger mean-median gap. Our model predicts the MEAN (CatBoost regression), so when our predicted mean is above the line (OVER), part of that edge may be mean-vs-median illusion rather than real OVER probability. For UNDER predictions, the skew actually HELPS us — median being lower than mean means UNDER wins more often than the mean suggests.
- **Claimed Edge:** Not quantified, but Unabated calls it the "major pitfall" — bettors using mean-based projections "will incorrectly favor Overs, resulting in fewer wins despite larger margins." This aligns with our persistent UNDER > OVER performance pattern.
- **Direction:** Primarily benefits UNDER (median < mean for right-skewed stats means UNDER hits more often), hurts OVER
- **Data Required:** Per-player scoring distribution (we have this from game history). Compute skewness and mean-median gap per player. Could create a feature: `scoring_skewness_last_N` or `mean_median_gap`. Use this to discount OVER edge on highly-skewed players and boost UNDER confidence.
- **Have It?** PARTIAL — We have full game-by-game player stats in BigQuery. We do NOT compute distributional statistics (skewness, kurtile ratios, mean-median gap). This is a derived feature from existing data.
- **Dead End Overlap:** NONE — This is a statistical property of individual player distributions, not a market signal. Tangentially related to our `volatile_scoring_over` signal but approaches from the opposite direction (skew hurts OVER, volatile_scoring_over says high variance = OVER).
- **Complexity:** LOW — Compute from existing player game logs. SQL: `APPROX_QUANTILES(points, 100)[OFFSET(50)]` for median, `AVG(points)` for mean, scipy skewness equivalent. Add as Phase 4 precompute feature. Could become both a feature and a signal filter.

### Angle: Injury Cascade Line Lag (Conditional Performance Windows)
- **Source:** [StatPick AI — How Sharps Beat Sportsbook Models](https://www.statpick.ai/blog/how-sharps-beat-sportsbook-models), [Hoop Heads — Injuries and Line Movement](https://hoopheadspod.com/the-role-of-injuries-in-nba-betting-how-line-movements-reflect-player-absences/), [BettorEdge — NBA Player Props Today](https://www.bettoredge.com/post/nba-player-props-today-how-to-find-value-boost-your-bets-daily)
- **Description:** When a high-usage teammate is ruled out, the remaining players' usage, shot attempts, and touches redistribute IMMEDIATELY — but sportsbooks are slow to adjust individual player prop lines because they process injury cascades manually. The "5:30-9 PM ET window" (when injury reports drop at 5 PM local time) is "prime money-making time." Sharp bettors pre-compute conditional projections (what does Player X average when Player Y is out?) and bet within 15-30 seconds of injury news. Books react fastest on the injured player's own line and spread, but secondary beneficiary props (teammate usage bumps) update much slower. Example: when a star is ruled out, the backup's minutes jump from 15 to 30 — books take 30-60 minutes to fully reprice the backup's line.
- **Claimed Edge:** Not quantified, but described as "one of the most scalable edges in the NBA" by StatPick. A 4-5 game role change window (before books adjust baseline) is explicitly cited.
- **Direction:** Primarily OVER for beneficiaries of usage redistribution
- **Data Required:** (1) Teammate injury status (we have injury data from `nbac_injury_report`), (2) Usage redistribution model: per-player conditional averages WITH vs WITHOUT each teammate, (3) Pre-computed conditional projections ready to fire when injury news breaks. We partially have this — our model uses injury-aware features — but we do NOT have pre-computed conditional lines or speed-to-market infrastructure.
- **Have It?** PARTIAL — We have injury data and it feeds into our model features. But we predict at a single point in time (morning batch) rather than reactively to injury news. By the time our daily predictions publish, books have already adjusted for most injuries. The edge is in SPEED (bet within seconds of news), which our batch architecture cannot capture.
- **Dead End Overlap:** Partially overlaps with our existing `stars_out` features and `opponent_depleted_under` filter, but those are about opponent injuries affecting our pick, not about teammate injuries creating beneficiary OVER opportunity.
- **Complexity:** HIGH — To truly exploit this angle, we would need: (1) real-time injury monitoring, (2) pre-computed conditional projections (what does each player average when each teammate is out), (3) automated near-real-time bet placement. Our batch architecture (predict in morning, export once) is fundamentally mismatched. However, a lighter version could work: pre-compute "injury sensitivity scores" as features — how much does each player's projection change when Key Teammate X is out? If that sensitivity is high and the teammate is questionable, weight the OVER.

### Angle: Low-Volume Prop Market Inefficiency (Rebounds/Assists/3PT vs Points)
- **Source:** [Covers — NBA Prop Betting Tips](https://www.covers.com/nba/prop-betting-tips), [Unabated — Fine Tune NBA Prop Strategy](https://unabated.com/articles/fine-tune-your-nba-prop-betting-strategy-using-unabated-nba), [OddsIndex — NBA Player Props Guide](https://oddsindex.com/guides/nba-player-props-guide)
- **Description:** Points props are the most popular and most efficiently priced. Books dedicate the most resources to pricing star player scoring lines. In contrast, rebounds, assists, 3-pointers, blocks, and steals are lower-volume markets with less scrutiny, higher variance, and slower line adjustment. Specifically: (1) 3-pointers and blocks/steals have the highest variance (most players between 0-2 range), creating larger pricing errors, (2) assists adjust slower than scoring after lineup changes, (3) role players' secondary stats (rebounds for a guard, assists for a center) are least attended to. Higher-impact players are more consistent (lower volatility), while lower-impact players are more volatile — creating a tier-specific efficiency gap.
- **Claimed Edge:** "5-10% edge from line shopping" on props generally. Less efficient props (assists, rebounds) have larger cross-book discrepancies.
- **Direction:** BOTH
- **Data Required:** We would need to expand from points-only props to multi-stat props (rebounds, assists, 3PT, PRA combos). Odds API supports these markets: `player_rebounds`, `player_assists`, `player_threes`, `player_blocks_steals`, `player_points_rebounds_assists`.
- **Have It?** NO — We currently only predict and scrape points props. Expanding to rebounds/assists/3PT would require: new feature engineering (rebound-specific features, assist-specific features), new model training, new scraper market parameters, and new Phase 4 precompute logic.
- **Dead End Overlap:** NONE — This is an entirely new prop type expansion, not a modification of our points model.
- **Complexity:** HIGH — Full pipeline expansion to new prop markets. This is a strategic direction change, not a signal or filter. However, it's the area with the most untapped edge according to market structure analysis.

### Angle: Game-Time Line Snap (Pre-Tip Book Alignment Check)
- **Source:** [TopEndSports — NBA Betting Strategy 2026](https://www.topendsports.com/betting-guides/sport-specific/nba/strategy.htm), [BetQL — NBA Line Movement](https://betql.co/nba/line-movement), [SportsBettingDime — Chasing Steam](https://www.sportsbettingdime.com/guides/strategy/chasing-steam/)
- **Description:** Just before tip-off, books raise their limits and absorb late sharp action. This is when the line is sharpest. If our model's prediction agrees with the direction the line moved from open to close (both say OVER), it's a strong confirmation. If our model disagrees (we say OVER, but the line dropped = market says UNDER), we have a conflict with the market's final assessment. This is a meta-filter: predictions aligned with closing-line direction have higher HR than predictions opposing it. The alignment check is: `sign(our_prediction - closing_line) == sign(closing_line - opening_line)`. When both point the same direction, the market and model agree.
- **Claimed Edge:** Per Pinnacle's data, opening-line bets have ~1.5% edge over closing. The REVERSE implication: if you're betting AGAINST the direction the line moved, you're swimming upstream against sharp money.
- **Direction:** BOTH
- **Data Required:** Opening line and closing line per player prop (same as Angle 1 — CLV tracking). Then compute: `line_direction = sign(closing - opening)` and `model_direction = recommendation`. When they agree, boost confidence; when they disagree, apply a penalty or filter.
- **Have It?** NO — Requires the same opening/closing line infrastructure as CLV tracking.
- **Dead End Overlap:** Loosely related to `line_rising_over` signal (which checks if line rose + model says OVER), but `line_rising_over` uses game-over-game delta, not intra-day opening-to-closing movement. The intra-day version would be stronger because it captures THAT DAY's sharp action.
- **Complexity:** MEDIUM — Same data infrastructure as CLV (Angle 1). The signal logic is simple: opening-to-closing direction agreement with model. Could be implemented as a signal (`market_aligned`) or as a filter (block predictions opposing closing-line direction).

---

## Priority Ranking

| Priority | Angle | Complexity | Data Gap | Expected Impact |
|----------|-------|-----------|----------|----------------|
| 1 | CLV Tracking + Game-Time Alignment | MEDIUM | Schedule 2 daily Odds API snapshots | HIGH — Best single predictor of long-term profitability per research |
| 2 | Mean-vs-Median Skew | LOW | Compute from existing BQ data | MEDIUM — Explains our UNDER > OVER pattern, zero data cost |
| 3 | Soft-Book Line Lag | LOW | Reclassify existing per-book data | MEDIUM — Directional upgrade to multi_book_line_std |
| 4 | Reverse Line Movement proxy | LOW-MEDIUM | Proxy from line direction + book consensus | LOW-MEDIUM — Partial proxy possible without new data |
| 5 | Low-Volume Prop Markets | HIGH | New prop types, features, models | HIGH long-term — Largest untapped edge per research |
| 6 | Injury Cascade Line Lag | HIGH | Real-time infra, conditional projections | HIGH but architecture mismatch |
| 7 | Steam Move Detection | HIGH | Multiple daily snapshots, high API cost | MEDIUM — Mostly captured by CLV if using 2 snapshots |

## Recommended Next Steps

1. **Immediate (no new data):** Compute mean-median gap and scoring skewness from existing player game logs. Add as Phase 4 precomputed features. Test as OVER discount / UNDER boost signal.

2. **Short-term (existing scraper, new schedule):** Add two daily Odds API snapshot runs — opening (~10 AM ET) and closing (~6 PM ET). Store both in a new `prop_line_snapshots` table. Compute CLV and market-alignment signals.

3. **Short-term (existing data, new logic):** Reclassify per-book lines by sharpness tier. Compute directional deviation from sharp consensus as a new signal metric. Upgrade `book_disagreement` signal with direction.

4. **Medium-term (new data):** Evaluate DraftKings "Most Bet" scraping for public betting proxy. Assess Action Network subscription cost vs. value for RLM detection.

5. **Long-term (strategic):** Evaluate expanding to rebounds/assists/3PT props as structurally less efficient markets.

## Data Source Reference

| Data Source | Access | Cost | Props Coverage |
|------------|--------|------|---------------|
| The Odds API (current) | API key | Paid (usage-based) | Points, rebounds, assists, 3PT, PRA |
| The Odds API Historical | API key | Additional cost per snapshot | Same as above, 5-min intervals |
| Action Network PRO | Subscription | ~$40/mo | Public betting %, money splits, game + props |
| DraftKings Network | Free web scrape | Free | "Most bet" props (popularity proxy, not money split) |
| TheSpread.com | Free | Free | Game-level public betting only (no props) |
| Outlier.bet | Subscription | ~$50/mo | Props-level public data, devigged odds |
| SportsBettingDime | Free | Free | Game-level trends only |

## Key Market Microstructure Insights

1. **No single sharp book for props.** Unlike sides/totals where Pinnacle sets the market, props are originated independently by FanDuel (their own models), and separately by DK/Caesars/BetMGM (who outsource origination from the same provider). This means FanDuel vs DK/Caesars divergence is the most meaningful signal of disagreement.

2. **Reaction window is 15-30 seconds.** Used to be 60 seconds. Speed advantage matters only for reactive strategies (injury cascade, steam chasing). For our batch architecture, the opportunities are in systematic mispricing (skew, CLV) not speed.

3. **Books price to median, models predict mean.** This structural mismatch between how we predict (regression → mean) and how books price (median) creates a systematic OVER bias in our edge calculations for right-skewed players. This may partially explain our OVER collapse pattern.

4. **Kambi is the softest.** Weight 0.627 vs DraftKings 1.046. If Kambi powers any books in our Odds API feed, their lines should be treated as the least informative for our sharp consensus calculation.

5. **Late money is sharper.** Books raise limits pre-tip, attracting sharp money. Opening-to-closing line direction reflects the market's final assessment incorporating all information. Our morning batch predictions cannot capture this, but we CAN capture it retrospectively for grading and signal validation.
