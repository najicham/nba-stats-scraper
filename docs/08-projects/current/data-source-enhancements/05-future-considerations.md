# Future Data Source Considerations

Lower priority enhancements to consider after completing Priority 1-4.

---

## Confirmed Lineups / Rotations

### What It Is
Pre-game confirmation of who's starting and expected rotation.

### Why It Could Help
- Starters play more minutes = more points opportunity
- Late scratches significantly affect predictions
- Rotation changes (player moved to bench) = minutes change

### Sources
- NBA.com official lineups (5-6 PM ET typically)
- RotoWire/RotoGrinders (aggregated, faster)
- Twitter/X (@Underdog NBA, beat reporters)

### Challenges
- Timing: Lineups confirmed close to game time
- Our predictions run earlier in the day
- Would need real-time adjustment pipeline

### Recommendation
**Medium priority** - Consider if we add real-time prediction updates.

---

## Teammate Availability Cascade Effects

### What It Is
When a star is out, how do teammates' stats change?

### Why It Could Help
- If LeBron is out, does Austin Reaves score more?
- Usage rate shifts when primary options are missing
- Could improve predictions for role players

### Implementation
```sql
-- Calculate teammate-out impact
SELECT
  player_name,
  teammate_out,
  AVG(points) as avg_points_with_teammate,
  AVG(points_without) as avg_points_without_teammate,
  (avg_without - avg_with) as teammate_out_boost
FROM player_game_logs
GROUP BY player_name, teammate_out
```

### Recommendation
**Medium priority** - Good feature but complex to implement well.

---

## Coach Rotation Tendencies

### What It Is
How different coaches manage minutes, especially in blowouts.

### Why It Could Help
- Some coaches pull starters early in blowouts (hurts props)
- Some coaches ride hot hands (helps props)
- Load management patterns vary by coach

### Sources
- Calculate from our existing play-by-play data
- No external source needed

### Recommendation
**Low priority** - Marginal impact, complex to model.

---

## Blowout / Garbage Time Risk

### What It Is
Probability that a game becomes a blowout, limiting star minutes.

### Why It Could Help
- Blowouts = starters play 28 min instead of 36
- Star players in easy matchups sometimes underperform props
- Vegas spread correlates with blowout risk

### Implementation
```python
def blowout_risk_score(spread: float, total: float) -> float:
    """
    Higher spread + higher total = more blowout risk.
    Returns 0-1 probability.
    """
    if abs(spread) >= 12:
        return 0.7  # High blowout risk
    elif abs(spread) >= 8:
        return 0.4
    elif abs(spread) >= 5:
        return 0.2
    return 0.1
```

### Recommendation
**Medium priority** - Simple to add, could help on lopsided matchups.

---

## Altitude Effects (Denver Games)

### What It Is
Denver plays at 5,280 feet - affects visiting teams.

### Why It Could Help
- Visiting teams show fatigue in Denver, especially late in games
- Some studies show 2-3% performance drop
- Particularly affects back-to-back visitors

### Implementation
Simple flag in game context:
```python
is_altitude_game = (home_team == "DEN" and away_team != "DEN")
altitude_factor = -0.5 if is_altitude_game else 0.0
```

### Recommendation
**Low priority** - Only affects ~40 games/season, marginal impact.

---

## National TV Game Adjustments

### What It Is
Games on ESPN/TNT tend to be closer, stars play more minutes.

### Why It Could Help
- National TV games are often marquee matchups
- Closer games = more crunch time minutes for stars
- Referees may call differently on national TV

### Sources
- ESPN schedule API
- Our existing schedule data includes broadcast info

### Recommendation
**Low priority** - Unclear if statistically significant.

---

## Day of Week / Time of Game Patterns

### What It Is
Performance patterns by day/time slot.

### Why It Could Help
- Sunday afternoon games may have tired players
- Late tips (10:30 PM ET) = fatigue for east coast teams
- Back-to-back afternoon games particularly tough

### Implementation
Add features:
```python
day_of_week = game_date.weekday()  # 0=Monday
is_afternoon_game = tip_time < "17:00"
is_late_game = tip_time >= "22:00"
```

### Recommendation
**Low priority** - Easy to add but likely noise, not signal.

---

## Historical Performance vs Specific Teams

### What It Is
Some players consistently perform better/worse vs certain teams.

### Why It Could Help
- Matchup-specific tendencies beyond just team defense
- "Revenge game" narrative sometimes real
- Division rival familiarity

### Current State
We have zone matchup analysis, but not player-vs-team history.

### Recommendation
**Low priority** - Sample sizes small, likely overfitting risk.

---

## Minutes Projections

### What It Is
Explicit projection of minutes played.

### Why It Could Help
- Points = PPM × Minutes
- If we can predict minutes better, we predict points better
- Captures rotation changes, blowout risk, foul trouble

### Implementation
Could be a separate model:
```
predicted_minutes = f(starter_flag, team_pace, spread, fatigue, injury_status)
predicted_points = predicted_minutes × points_per_minute
```

### Recommendation
**Medium-High priority** - Minutes variance is huge source of prediction error.

---

## Summary Priority Matrix

| Enhancement | Impact | Effort | Priority |
|-------------|--------|--------|----------|
| Referee tendencies | High | Medium | **P1** |
| Player travel (complete) | Medium | Low | **P2** |
| Tracking stats | High | Medium | **P3** |
| Line movement/CLV | High | Medium | **P4** |
| Minutes projection model | High | High | P5 |
| Blowout risk | Medium | Low | P6 |
| Teammate cascade | Medium | High | P7 |
| Confirmed lineups | Medium | High | P8 |
| Everything else | Low | Varies | Backlog |

---

## Data Sources NOT Recommended

### Social Media Sentiment
- **Why not:** Noisy, requires NLP pipeline, unclear signal
- **Alternative:** Trust injury reports, ignore narratives

### Weather Data
- **Why not:** NBA is indoors
- **Exception:** None

### Real-Time In-Game Data
- **Why not:** Our use case is pre-game predictions
- **Exception:** If we expand to live betting, reconsider

### Expensive Enterprise APIs (Second Spectrum direct)
- **Why not:** $$$, NBA.com provides derived data free
- **Alternative:** Use NBA.com tracking endpoints
