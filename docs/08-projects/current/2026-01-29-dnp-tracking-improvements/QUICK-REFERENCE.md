# DNP Tracking Quick Reference

## InjuryFilter v2.1 Usage

### Single Player Check

```python
from predictions.shared.injury_filter import get_injury_filter

filter = get_injury_filter()

# Check injury report (existing v2.0)
status = filter.check_player(player_lookup, game_date)
if status.should_skip:
    print("Skip: Player listed as OUT")
elif status.has_warning:
    print(f"Warning: {status.injury_status}")

# Check DNP history (new v2.1)
dnp = filter.check_dnp_history(player_lookup, game_date)
if dnp.has_dnp_risk:
    print(f"DNP Risk: {dnp.dnp_count}/{dnp.games_checked} games")
    print(f"Category: {dnp.risk_category}")
    print(f"Last DNP: {dnp.days_since_last_dnp} days ago")

# Combined check (v2.1)
status, dnp = filter.get_combined_risk(player_lookup, game_date)
```

### Batch Check

```python
players = ['lebronjames', 'stephencurry', 'kevindunrant']
game_date = date(2026, 1, 29)

# Batch injury check
statuses = filter.check_players_batch(players, game_date)

# Batch DNP history check
dnp_histories = filter.check_dnp_history_batch(players, game_date)

# Batch combined check
combined = filter.get_combined_risk_batch(players, game_date)
for player, (status, dnp) in combined.items():
    print(f"{player}: injury={status.injury_status}, dnp_risk={dnp.has_dnp_risk}")
```

## DNPHistory Fields

| Field | Type | Description |
|-------|------|-------------|
| `player_lookup` | str | Player identifier |
| `game_date` | date | Game date checked |
| `games_checked` | int | Number of recent games analyzed |
| `dnp_count` | int | DNPs in the window |
| `dnp_rate` | float | DNP rate (0.0-1.0) |
| `recent_dnp_reasons` | List[str] | Last few DNP reasons |
| `last_dnp_date` | date | Most recent DNP |
| `has_dnp_risk` | bool | True if 2+ DNPs in window |
| `risk_category` | str | 'injury', 'coach_decision', etc. |
| `days_since_last_dnp` | int | Days since last DNP |

## Configuration

```python
# In InjuryFilter class
DNP_HISTORY_WINDOW = 5   # Games to check
DNP_RISK_THRESHOLD = 2   # DNPs to trigger risk flag
```

## ML Feature: dnp_rate

Feature 33 in `ml_feature_store_v2`:
- Range: 0.0 to 1.0
- Calculation: DNPs / games in last 10 games
- Default: 0.0 if insufficient history

## BigQuery Queries

### Check DNP patterns
```sql
SELECT
  player_lookup,
  COUNT(*) as games,
  SUM(CASE WHEN is_dnp THEN 1 ELSE 0 END) as dnps,
  ROUND(SUM(CASE WHEN is_dnp THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as dnp_pct
FROM nba_analytics.player_game_summary
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
GROUP BY player_lookup
HAVING SUM(CASE WHEN is_dnp THEN 1 ELSE 0 END) >= 2
ORDER BY dnp_pct DESC
```

### Check DNP reasons distribution
```sql
SELECT
  dnp_reason_category,
  COUNT(*) as count
FROM nba_analytics.player_game_summary
WHERE game_date >= '2026-01-28'
  AND is_dnp = true
GROUP BY dnp_reason_category
ORDER BY count DESC
```

## Monitoring

Check worker logs for DNP risk warnings:
```bash
gcloud logging read 'resource.labels.service_name="prediction-worker" AND textPayload:"DNP risk"' \
  --limit=20 --freshness=2h
```
