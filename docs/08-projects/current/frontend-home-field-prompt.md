# Frontend Prompt: Use `home` field for matchup display

## Context

The `best-bets/all.json` API now includes a `home` boolean field on every pick object — both in `today[]` and in `weeks[].days[].picks[]`.

## Data shape

```jsonc
// today[] and weeks[].days[].picks[]
{
  "player": "LeBron James",
  "player_lookup": "lebron_james_LAL",
  "team": "LAL",
  "opponent": "BOS",
  "home": true,        // ← NEW FIELD
  "direction": "OVER",
  "stat": "PTS",
  "line": 25.5,
  "edge": 4.2,
  // ... rest of pick fields
}
```

## What changed

- `home: true` → player's team is the home team
- `home: false` → player's team is the away team
- Field is always present (boolean, never null)
- Works for both today's picks and all historical picks in the weeks array

## Frontend task

Use the `home` field to display the matchup correctly on pick cards:

- `home: true` → show **"LAL vs BOS"** (team listed first, opponent second)
- `home: false` → show **"LAL @ BOS"** (team listed first with @ separator, opponent is the home team)

The `team` field is always the player's team. The display format should be:

```
{team} {home ? "vs" : "@"} {opponent}
```

This applies everywhere picks are rendered — the today hero section and the weekly history cards.
