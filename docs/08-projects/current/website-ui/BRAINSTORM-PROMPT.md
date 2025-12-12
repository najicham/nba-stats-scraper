# NBA Props Website UI Brainstorm Prompt

Copy everything below the line into a new Claude chat for UI brainstorming.

---

## Context

I'm building a website for NBA player points predictions. I have a complete data pipeline that generates daily predictions and tracks accuracy. I need help brainstorming the UI/UX design.

### Primary Goal
Give users predictions and picks for NBA player points props (betting lines)

### Secondary Goal
Be a good source of general NBA player/team data for casual fans who may not be betting

### Future Goals (not now)
- Premium features for paying customers
- Fantasy games or group challenges

## Available Data

I have JSON APIs that provide:

**Daily Predictions** (`/predictions/today.json`)
- Every player with an upcoming game
- Predicted points, confidence score (0-100%)
- Current betting line, edge (predicted - line)
- Recommendation: OVER, UNDER, or PASS
- Key factors explaining the prediction
- System agreement score (do multiple models agree?)

**Best Bets** (`/best-bets/today.json`)
- Top 15 ranked picks by composite score
- Ranked by: confidence × edge × historical accuracy
- Includes rationale for each pick

**Daily Results** (`/results/{date}.json`)
- Yesterday's predictions vs actual outcomes
- Win/loss for each prediction
- Summary stats: win rate, accuracy metrics

**Player Profiles** (`/players/{name}.json`)
- Historical accuracy for predictions on this player
- Win rate, average error, bias (over/under-predict tendency)
- Last 20 predictions with outcomes
- Breakdown by recommendation type

**System Performance** (`/systems/performance.json`)
- 5 prediction systems tracked
- Rolling metrics: 7-day, 30-day, season
- Win rates, accuracy, which system is best

**Additional data I can add:**
- Streaks (players hitting over/under X games in a row)
- Leaderboards (top scorers, most predictable players, etc.)
- Team-level stats (offense/defense ratings)
- Game schedule with broadcast info

## My Initial View Ideas

### View 1: Player Grid (Today's Games)
A filterable grid showing all players with games today. Columns: player, team, opponent, line, prediction, confidence, recommendation. Click a player to see details in a slide-out panel (like Airbnb on desktop).

### View 2: Streaks
Show players on hot/cold streaks. Maybe 3+ games hitting over, or 3+ games where our prediction was correct. Not sure exactly what makes this valuable.

### View 3: League-Wide / System Stats
Show how the prediction systems are performing. Maybe leaderboards. Maybe team-level trends.

## Design Constraints

1. **Mobile-first** - But there's a lot of data, so this is challenging
2. **Slide-out panel on desktop** - Like Airbnb, click a row and details slide in from the right
3. **Casual fans AND bettors** - Need to serve both audiences
4. **Keep it simple for v1** - Can add complexity later

## Questions I Need Help With

1. **Information Architecture**: Are 3 separate views the right approach? Should it be structured differently? Maybe tabs within a single view? Maybe a different mental model entirely?

2. **Mobile Layout**: How do I show a data-heavy grid on mobile? Cards instead of rows? Horizontal scroll? Progressive disclosure?

3. **Prediction vs Information Balance**: How do I serve bettors (who want picks) AND casual fans (who want stats) without confusing either?

4. **The "Home" Experience**: What should users see first? Today's best bets? A dashboard? The full player grid?

5. **Streaks View Value**: Is a streaks view actually useful? What would make it compelling? Or should streak info be integrated into the player grid/detail instead?

6. **Player Detail Design**: What information is most important in the player detail panel? How should it be organized?

7. **Progressive Disclosure**: What should be visible at a glance vs hidden behind clicks/taps?

8. **Empty States**: What if there are no games today? What about during off-season?

## What I Want From This Brainstorm

- Challenge my assumptions about the 3-view structure
- Explore alternative information architectures
- Think through the mobile experience specifically
- Identify what's essential vs nice-to-have for v1
- Maybe sketch out a few different approaches to compare

I'm open to completely rethinking the structure if there's a better way. Help me think through this before I commit to building something.
