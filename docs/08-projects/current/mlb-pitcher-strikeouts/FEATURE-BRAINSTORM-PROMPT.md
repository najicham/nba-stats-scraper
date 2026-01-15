# Feature Brainstorming Prompt: MLB Pitcher Strikeout Predictions

## Context

I'm building a machine learning model to predict whether MLB pitchers will go OVER or UNDER their strikeout betting line. I need help brainstorming additional features, statistics, or data sources that could improve prediction accuracy.

## Current Performance

| Model Version | Hit Rate | Notes |
|---------------|----------|-------|
| V1.5 Regression (predict K count) | 52.98% | Barely profitable |
| V2 Classifier (direct O/U prediction) | **65.35%** | Much better, needs validation |
| High Confidence bets only | **75.7%** | When model is confident |
| Breakeven threshold | 52.4% | At -110 odds |

## Key Discovery: The Market is Efficient

We found that simple "trend following" doesn't work because Vegas adjusts lines:
- When a pitcher has gone OVER in 4+ of last 5 games, their line is set **1.16 K BELOW** their recent average
- When they've gone UNDER in 4+ of last 5 games, their line is set **1.31 K ABOVE** their recent average

**The market already prices in obvious patterns.** We need to find information the market underweights or doesn't have.

## Features We Currently Use (28 total)

### Pitcher Performance Features
- `k_avg_last_3`, `k_avg_last_5`, `k_avg_last_10` - Rolling strikeout averages
- `k_std_last_10` - Strikeout volatility/consistency
- `season_k_per_9` - Season K/9 rate
- `ip_avg_last_5` - Average innings pitched (affects K opportunity)

### Season/Workload Features
- `season_era`, `season_whip` - Overall effectiveness
- `season_games_started` - How deep into season
- `days_rest` - Rest between starts
- `games_last_30_days` - Recent workload
- `pitch_count_avg_last_5` - Pitch count trends
- `season_innings_total` - Cumulative fatigue indicator

### Context Features
- `is_home` - Home/away indicator
- `opponent_team_k_rate` - How much the opposing team strikes out
- `ballpark_k_factor` - Park effects on strikeouts
- `month_of_season` - Seasonality (April vs August)
- `is_postseason` - Playoff indicator

### Betting/Projection Features
- `betting_line` - The actual O/U line set by Vegas
- `bp_projection` - BettingPros model's K prediction
- `projection_diff` - Gap between projection and line
- `over_implied_prob` - Market odds converted to probability
- `k_avg_vs_line` - How far recent K avg is from line

## Feature Ideas We Haven't Implemented Yet

### 1. Umpire Data
Different umpires have different strike zones. Some umps favor pitchers (more called strikes = more Ks).
- Umpire historical K-rate
- Umpire's average called strike zone size
- Home plate umpire for this specific game

### 2. Weather & Environment
- **Temperature** - Cold weather affects grip on breaking balls
- **Humidity** - Affects ball movement
- **Wind** - Less relevant for Ks but affects pitcher approach
- **Altitude** - Denver (Coors Field) is notoriously different
- **Day vs Night** - Different visibility conditions

### 3. Pitcher-Specific Patterns
- How does this specific pitcher perform vs LEFT-heavy lineups vs RIGHT-heavy?
- Pitcher's K-rate in high-leverage situations
- First time through order vs second/third time K-rates
- Pitcher's performance on specific days rest (4 days vs 5 days vs 6+)

### 4. Opponent Lineup Specifics
- Today's actual starting lineup K-rates (not team average)
- Handedness matchup (LHP vs lineup with many LHB)
- Opponent's recent K-rate trend (slumping = more Ks?)
- DH vs pitcher batting (AL vs NL)

### 5. Line Movement & Sharp Money
- Opening line vs current line (has it moved?)
- Direction and magnitude of line movement
- Sharp money indicators (where are professional bettors?)
- Time since line was posted

### 6. Situational Factors
- Pitcher's record/performance in current ballpark
- Divisional matchup (familiarity cuts both ways)
- Game importance (playoff race implications)
- Travel (coast-to-coast trip = fatigue?)

### 7. Advanced Pitcher Metrics
- Swinging strike rate (SwStr%)
- Called strike + whiff rate (CSW%)
- Chase rate (how often batters swing at pitches outside zone)
- Spin rate on breaking balls
- Fastball velocity trend (declining = fatigue)

### 8. Batter-Specific Analysis
- How do TODAY's specific batters perform vs this pitcher historically?
- Lineup's collective performance vs pitcher's pitch mix (lots of fastballs vs fastball hitters?)

## What I'm Looking For

1. **Novel features** the market might not fully price in
2. **Data sources** that are publicly available but underutilized
3. **Interaction effects** between features (e.g., "high altitude + cold weather + breaking ball pitcher")
4. **Situations** where the market is likely to be wrong
5. **Red flags** - situations where we should NOT bet even if model is confident

## Specific Questions

1. What pitcher-specific patterns might persist game-to-game that Vegas doesn't fully account for?

2. Are there any publicly available advanced metrics (Statcast, FanGraphs, Baseball Savant) that correlate strongly with strikeout performance?

3. What environmental or situational factors most affect strikeout probability?

4. Are there any "market inefficiency" situations in MLB betting you're aware of (e.g., certain teams, certain times of year, certain line ranges)?

5. What data could indicate a pitcher is "due" for regression (positive or negative) before the market adjusts?

6. Any insights on how to identify when a pitcher's underlying stuff has changed (injury, mechanical adjustment, new pitch) before it shows in traditional stats?

## Constraints

- Need data that's available BEFORE game time (no in-game stats)
- Prefer data sources that can be automated/scraped
- Model runs daily for that day's games
- Currently focused on starting pitchers only (not relievers)

## Your Task

Please suggest:
1. **5-10 specific features** you think would have predictive value
2. **Data sources** where I could find this information
3. **Your reasoning** for why the market might underweight this information
4. Any **edge cases or caveats** to watch out for

Thank you for any insights!
