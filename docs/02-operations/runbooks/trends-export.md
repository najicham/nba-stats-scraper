# Trends v2 Export System Runbook

**Created:** 2025-12-15
**Last Updated:** 2025-12-15
**Status:** Active

---

## Overview

The Trends v2 export system generates JSON files for the NBA Props Platform Trends page. It consists of **6 independent exporters** that analyze player and team performance data to identify betting trends and insights.

All exporters query BigQuery analytics tables and publish JSON files to Google Cloud Storage for consumption by the website.

### The 6 Exporters

| Exporter | File | Refresh | Description |
|----------|------|---------|-------------|
| **Who's Hot/Cold** | `whos-hot-v2.json` | Daily 6 AM | Players on hot/cold streaks based on heat score |
| **Bounce-Back Watch** | `bounce-back.json` | Daily 6 AM | Players due for regression after underperforming |
| **What Matters Most** | `what-matters.json` | Weekly Mon 6 AM | Factor impacts by player archetype (stars, scorers, etc) |
| **Team Tendencies** | `team-tendencies.json` | Bi-weekly Mon 6 AM | Pace, defense zones, home/away, B2B impacts |
| **Quick Hits** | `quick-hits.json` | Weekly Wed 8 AM | 8 rotating bite-sized stats/insights |
| **Deep Dive** | `deep-dive-current.json` | Monthly 1st | Featured monthly analysis promo card |

---

## Live Data URLs

All exported JSON files are publicly accessible via GCS:

```
https://storage.googleapis.com/nba-props-platform-api/v1/trends/whos-hot-v2.json
https://storage.googleapis.com/nba-props-platform-api/v1/trends/bounce-back.json
https://storage.googleapis.com/nba-props-platform-api/v1/trends/what-matters.json
https://storage.googleapis.com/nba-props-platform-api/v1/trends/team-tendencies.json
https://storage.googleapis.com/nba-props-platform-api/v1/trends/quick-hits.json
https://storage.googleapis.com/nba-props-platform-api/v1/trends/deep-dive-current.json
```

**Cache Headers:**
- Daily exports: `max-age=3600` (1 hour)
- Weekly/bi-weekly exports: `max-age=43200` (12 hours)
- Monthly exports: `max-age=86400` (24 hours)

---

## Manual Export Commands

All exports are triggered through the `daily_export.py` script with the `--only` flag.

### Export All Trends

```bash
# Export all 6 trends exporters for today
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py \
  --date $(date +%Y-%m-%d) \
  --only trends-all
```

### Export by Frequency Groups

```bash
# Daily exporters only (hot/cold + bounce-back)
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py \
  --date $(date +%Y-%m-%d) \
  --only trends-daily

# Weekly exporters only (what-matters + team + quick-hits)
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py \
  --date $(date +%Y-%m-%d) \
  --only trends-weekly
```

### Export Individual Exporters

```bash
# Who's Hot/Cold
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py \
  --date 2024-12-15 \
  --only trends-hot-cold

# Bounce-Back Watch
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py \
  --date 2024-12-15 \
  --only trends-bounce-back

# What Matters Most
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py \
  --date 2024-12-15 \
  --only trends-what-matters

# Team Tendencies
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py \
  --date 2024-12-15 \
  --only trends-team

# Quick Hits
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py \
  --date 2024-12-15 \
  --only trends-quick-hits

# Deep Dive
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py \
  --date 2024-12-15 \
  --only trends-deep-dive
```

### Export Specific Date

```bash
# Export for specific date (useful for backfills)
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py \
  --date 2024-12-10 \
  --only trends-all
```

### Dry Run / Testing

```bash
# The exporter doesn't have a dry-run flag, but you can:
# 1. Check logs for errors without verifying GCS upload
# 2. Use a different date to avoid overwriting production files

PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py \
  --date 2024-01-01 \
  --only trends-hot-cold
```

---

## Export Schedule

### Daily Exporters (6 AM ET)

**Run every day:**
- `trends-hot-cold` - Who's Hot/Cold
- `trends-bounce-back` - Bounce-Back Watch

**Purpose:** Identify players with recent momentum for daily bettors

**Automation:** Scheduled via Cloud Scheduler (daily 6 AM ET)

### Weekly Exporters

**Monday 6 AM ET:**
- `trends-what-matters` - What Matters Most (factor impacts by archetype)
- `trends-team` - Team Tendencies (pace, defense, B2B)

**Wednesday 8 AM ET:**
- `trends-quick-hits` - Quick Hits (8 rotating stats)

**Purpose:** Weekly insights updated on fresh slate (Monday) and mid-week (Wednesday)

**Automation:** Scheduled via Cloud Scheduler (weekly)

### Bi-Weekly Exporters

**Every other Monday 6 AM ET:**
- `trends-team` - Team Tendencies

**Purpose:** Team data changes more slowly than player data

**Note:** Currently runs weekly but designed to support bi-weekly cadence

### Monthly Exporters

**1st of month:**
- `trends-deep-dive` - Deep Dive Current (monthly featured analysis)

**Purpose:** Featured monthly content/promo card

**Automation:** Scheduled via Cloud Scheduler (monthly 1st)

---

## Exporter Implementation Details

### 1. Who's Hot/Cold (`WhosHotColdExporter`)

**File:** `data_processors/publishing/whos_hot_cold_exporter.py`

**What it does:**
- Calculates "heat score" for all qualifying players
- Heat Score = 50% hit_rate + 25% streak_factor + 25% margin_factor
- Returns top 10 hot and top 10 cold players

**Key parameters:**
- `min_games`: 5 (default)
- `lookback_days`: 30 (default)
- `top_n`: 10 (default)

**Data source:** `nba_analytics.player_game_summary`

**Sample output:**
```json
{
  "hot": [
    {
      "rank": 1,
      "player_lookup": "jordanclarkson",
      "player_name": "Jordan Clarkson",
      "team": "UTA",
      "heat_score": 0.85,
      "hit_rate": 0.75,
      "current_streak": 5,
      "streak_type": "OVER",
      "avg_margin": 3.2,
      "games_played": 10
    }
  ]
}
```

### 2. Bounce-Back Watch (`BounceBackExporter`)

**File:** `data_processors/publishing/bounce_back_exporter.py`

**What it does:**
- Identifies players who had a bad game (10+ points below season average)
- Calculates historical bounce-back rate after similar bad games
- Returns players most likely to bounce back

**Key parameters:**
- `shortfall_threshold`: 10 points (default)
- `min_sample`: 3 historical bad games (minimum)

**Data source:** `nba_analytics.player_game_summary`

**Sample output:**
```json
{
  "bounce_back_candidates": [
    {
      "rank": 1,
      "player_name": "Stephen Curry",
      "last_game": {
        "date": "2024-12-14",
        "points": 12,
        "opponent": "LAL"
      },
      "season_average": 26.5,
      "shortfall": 14.5,
      "bounce_back_rate": 0.786,
      "bounce_back_sample": 14,
      "significance": "high"
    }
  ]
}
```

### 3. What Matters Most (`WhatMattersExporter`)

**File:** `data_processors/publishing/what_matters_exporter.py`

**What it does:**
- Analyzes how factors (rest, home/away, B2B) impact different player archetypes
- Archetypes: stars (22+ PPG), scorers (15-22 PPG), rotation (8-15 PPG), role players (<8 PPG)
- Generates key insights comparing archetypes

**Key parameters:**
- Lookback: 365 days (full season)
- Min games per player: 20

**Data sources:**
- `nba_analytics.player_game_summary`
- `nba_analytics.team_offense_game_summary`

**Sample output:**
```json
{
  "archetypes": {
    "star": {
      "description": "22+ PPG stars",
      "player_count": 35,
      "overall_over_pct": 51.2,
      "factors": {
        "rest": {
          "b2b": {"games": 234, "over_pct": 48.5},
          "rested": {"games": 456, "over_pct": 52.1}
        },
        "home_away": {
          "home": {"games": 350, "over_pct": 53.2},
          "away": {"games": 340, "over_pct": 49.1}
        }
      }
    }
  },
  "key_insights": [
    "Stars perform better on B2Bs (52.1% vs 48.5% on 2+ rest)"
  ]
}
```

### 4. Team Tendencies (`TeamTendenciesExporter`)

**File:** `data_processors/publishing/team_tendencies_exporter.py`

**What it does:**
- Analyzes team-level factors affecting player props
- Pace kings (fastest) vs grinders (slowest)
- Defense by zone (paint, perimeter)
- Home/away splits
- Back-to-back vulnerability

**Key parameters:**
- Pace lookback: 30 days
- Defense lookback: 30 days
- Home/away lookback: 60 days
- B2B lookback: 90 days

**Data sources:**
- `nba_analytics.team_offense_game_summary`
- `nba_precompute.team_defense_zone_analysis`

**Sample output:**
```json
{
  "pace": {
    "kings": [
      {
        "team": "SAC",
        "pace": 102.5,
        "vs_league": 4.2,
        "insight": "High-scoring environment"
      }
    ]
  },
  "defense_by_zone": {
    "paint": {
      "best": [{"team": "BOS", "dfg_pct": 52.1}]
    }
  }
}
```

### 5. Quick Hits (`QuickHitsExporter`)

**File:** `data_processors/publishing/quick_hits_exporter.py`

**What it does:**
- Generates bite-sized stats across multiple categories
- Selects 8 most interesting stats (deviation from 50%)
- Categories: day of week, situational (rest), home/away, player tiers

**Key parameters:**
- `num_stats`: 8
- `min_sample`: 50 games
- Lookback: 90 days

**Data sources:**
- `nba_analytics.player_game_summary`
- `nba_analytics.team_offense_game_summary`

**Sample output:**
```json
{
  "stats": [
    {
      "id": "sunday_overs",
      "category": "day_of_week",
      "headline": "Sunday Surge",
      "stat": "54.2%",
      "description": "OVER hit rate on Sundays",
      "sample_size": 342,
      "trend": "positive",
      "context": "vs 49.8% overall (+4.4%)"
    }
  ]
}
```

### 6. Deep Dive (`DeepDiveExporter`)

**File:** `data_processors/publishing/deep_dive_exporter.py`

**What it does:**
- Generates monthly featured analysis promo card
- Rotates through monthly topics (e.g., "January Effect", "All-Star Break Impact")
- Simple exporter with minimal queries (mostly static content)

**Key parameters:**
- Monthly topics defined in `MONTHLY_TOPICS` dict
- Focus areas: rest_impact, schedule_density, playoff_race, etc.

**Sample output:**
```json
{
  "month": "December 2024",
  "title": "December Deep Dive",
  "subtitle": "Rest patterns and holiday performance",
  "hero_stat": {
    "value": "54%",
    "label": "OVER rate on 2+ rest days",
    "context": "vs 48% on back-to-backs (+6%)"
  },
  "teaser": "Our analysis of rest patterns reveals...",
  "slug": "rest-impact-december-2024"
}
```

---

## Troubleshooting

### Export Failed: "No data available"

**Symptom:** Exporter completes but returns empty arrays

**Cause:** Insufficient data in analytics tables for the query period

**Fix:**
1. Check if analytics tables have recent data:
   ```bash
   bq query --use_legacy_sql=false "
   SELECT MAX(game_date) as latest_game
   FROM \`nba-props-platform.nba_analytics.player_game_summary\`
   "
   ```
2. Verify the date you're exporting is within the data range
3. Check if upstream Phase 3/4 processors have run for recent dates

### Export Failed: BigQuery Permission Denied

**Symptom:** `403 Forbidden` error from BigQuery

**Cause:** Service account lacks BigQuery read permissions

**Fix:**
1. Verify service account has `roles/bigquery.dataViewer` on project
2. Check if running locally: ensure `GOOGLE_APPLICATION_CREDENTIALS` is set
3. If in Cloud Run: verify service account is correctly configured

### Export Succeeded but GCS File Not Updated

**Symptom:** Export logs show success but JSON file timestamp unchanged

**Cause:** GCS upload failed or cache serving stale file

**Fix:**
1. Check GCS permissions:
   ```bash
   gsutil ls -L gs://nba-props-platform-api/v1/trends/
   ```
2. Verify service account has `roles/storage.objectCreator`
3. Check cache headers - may need to wait for cache expiry or purge CDN cache
4. Manually verify file content:
   ```bash
   gsutil cat gs://nba-props-platform-api/v1/trends/whos-hot-v2.json | jq '.generated_at'
   ```

### "No players qualify" for Hot/Cold

**Symptom:** Hot/Cold export shows 0 qualifying players

**Cause:** `min_games` threshold too high for recent data

**Fix:**
1. Check how many players have sufficient games:
   ```sql
   SELECT COUNT(DISTINCT player_lookup) as players
   FROM `nba_analytics.player_game_summary`
   WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
     AND over_under_result IN ('OVER', 'UNDER')
   GROUP BY player_lookup
   HAVING COUNT(*) >= 5
   ```
2. Lower `min_games` parameter if early in season
3. Increase `lookback_days` to expand window

### Bounce-Back Shows No Candidates

**Symptom:** Bounce-back export returns empty candidates array

**Cause:** No players had bad games (10+ below average) in last game

**Fix:**
1. This is expected behavior - not every day has bounce-back candidates
2. Lower `shortfall_threshold` to be more permissive (e.g., 8 points instead of 10)
3. Verify season averages are calculating correctly:
   ```sql
   SELECT player_lookup, AVG(points) as season_avg, COUNT(*) as games
   FROM `nba_analytics.player_game_summary`
   WHERE season_year = 2024
   GROUP BY player_lookup
   HAVING COUNT(*) >= 10
   ORDER BY season_avg DESC
   LIMIT 10
   ```

### Quick Hits Returning Fewer Than 8 Stats

**Symptom:** Quick Hits export has < 8 stats in output

**Cause:** Insufficient sample sizes or no significant deviations from 50%

**Fix:**
1. Check `min_sample` threshold (default 50) - lower if needed
2. Verify sufficient game data exists across categories
3. This is acceptable early in season when sample sizes are small
4. Stats are sorted by "interestingness" (deviation from 50%) - may legitimately have < 8 qualifying stats

### Deep Dive Using Wrong Month

**Symptom:** Deep Dive shows wrong monthly topic

**Cause:** `as_of_date` parameter determines which month's topic to show

**Fix:**
1. Deep Dive uses current month to select topic from `MONTHLY_TOPICS` dict
2. If exporting for past/future date, topic will match that month
3. This is expected behavior - no fix needed
4. If specific months missing from `MONTHLY_TOPICS`, defaults to December topic

### Export Running Extremely Slow

**Symptom:** Export takes > 5 minutes to complete

**Cause:** Large date ranges or unoptimized queries

**Fix:**
1. Check BigQuery query performance in console
2. Verify tables are properly partitioned and clustered
3. Consider reducing lookback windows (e.g., 90 days instead of 365)
4. Check if running during high BigQuery load period
5. Review query execution plan for full table scans

### Cannot Import Exporter Module

**Symptom:** `ModuleNotFoundError: No module named 'data_processors.publishing'`

**Cause:** `PYTHONPATH` not set correctly

**Fix:**
```bash
# Set PYTHONPATH to project root
export PYTHONPATH=/home/naji/code/nba-stats-scraper
# Or use inline:
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py --only trends-all
```

---

## JSON Schema Reference

### Common Fields

All exporters include these standard fields:

```typescript
interface BaseExport {
  generated_at: string;      // ISO 8601 timestamp
  as_of_date: string;         // YYYY-MM-DD
}
```

### Who's Hot/Cold Schema

```typescript
interface WhosHotColdExport {
  generated_at: string;
  as_of_date: string;
  time_period: string;              // e.g., "last_30_days"
  min_games: number;
  total_qualifying_players: number;
  hot: HotColdPlayer[];
  cold: HotColdPlayer[];
  league_average: {
    hit_rate: number;
    avg_margin: number;
  };
}

interface HotColdPlayer {
  rank: number;
  player_lookup: string;
  player_name: string;
  team: string;
  heat_score: number;               // 0-1 scale
  hit_rate: number;                 // 0-1 scale
  current_streak: number;
  streak_type: "OVER" | "UNDER";
  avg_margin: number;               // Points above/below line
  games_played: number;
  playing_tonight: boolean;         // Currently always false (needs schedule data)
  tonight_opponent: string | null;
  tonight_game_time: string | null;
}
```

### Bounce-Back Schema

```typescript
interface BounceBackExport {
  generated_at: string;
  as_of_date: string;
  shortfall_threshold: number;
  total_candidates: number;
  bounce_back_candidates: BounceBackCandidate[];
  league_baseline: {
    avg_bounce_back_rate: number;
    sample_size: number;
  };
}

interface BounceBackCandidate {
  rank: number;
  player_lookup: string;
  player_name: string;
  team: string;
  last_game: {
    date: string;
    points: number;
    opponent: string;
  };
  season_average: number;
  shortfall: number;                // Points below average
  bounce_back_rate: number;         // Historical rate (0-1)
  bounce_back_sample: number;       // Historical bad games count
  significance: "high" | "medium" | "low";
  playing_tonight: boolean;
  tonight_opponent: string | null;
}
```

### What Matters Most Schema

```typescript
interface WhatMattersExport {
  generated_at: string;
  as_of_date: string;
  archetypes: {
    [key: string]: Archetype;       // star, scorer, rotation, role_player
  };
  key_insights: string[];
}

interface Archetype {
  description: string;
  player_count: number;
  example_players: string[];
  overall_over_pct: number | null;
  factors: {
    rest: {
      [key: string]: FactorStat;    // b2b, one_day, rested
    };
    home_away: {
      [key: string]: FactorStat;    // home, away
    };
  };
}

interface FactorStat {
  games: number;
  over_pct: number;
}
```

### Team Tendencies Schema

```typescript
interface TeamTendenciesExport {
  generated_at: string;
  as_of_date: string;
  pace: {
    kings: PaceTeam[];              // Top 5 fastest
    grinders: PaceTeam[];           // Top 5 slowest
    league_average: number | null;
  };
  defense_by_zone: {
    paint: {
      best: DefenseTeam[];
      worst: DefenseTeam[];
    };
    perimeter: {
      best: DefenseTeam[];
      worst: DefenseTeam[];
    };
  };
  home_away: {
    home_dominant: HomeAwayTeam[];
    road_warriors: HomeAwayTeam[];
  };
  back_to_back: {
    vulnerable: B2BTeam[];
    resilient: B2BTeam[];
  };
}

interface PaceTeam {
  team: string;
  pace: number;
  games: number;
  avg_points: number;
  vs_league: number;
  insight: string;
}

interface DefenseTeam {
  team: string;
  dfg_pct: number;                  // Defensive FG% (percentage, not 0-1)
  opp_ppg: number;
  games: number;
  insight: string;
}

interface HomeAwayTeam {
  team: string;
  home_ppg: number;
  away_ppg: number;
  differential: number;
  insight: string;
}

interface B2BTeam {
  team: string;
  b2b_ppg: number;
  rested_ppg: number;
  impact: number;
  b2b_games: number;
  insight: string;
}
```

### Quick Hits Schema

```typescript
interface QuickHitsExport {
  generated_at: string;
  as_of_date: string;
  stats: QuickStat[];
  total_available: number;
  refresh_note: string;
}

interface QuickStat {
  id: string;
  category: "day_of_week" | "situational" | "player_type";
  headline: string;
  stat: string;                     // e.g., "54.2%"
  description: string;
  sample_size: number;
  trend: "positive" | "negative" | "neutral";
  context: string;
}
```

### Deep Dive Schema

```typescript
interface DeepDiveExport {
  generated_at: string;
  month: string;                    // e.g., "December 2024"
  title: string;
  subtitle: string;
  hero_stat: {
    value: string;
    label: string;
    context: string;
  };
  teaser: string;
  slug: string;
  cta: string;
}
```

---

## Monitoring

### Daily Health Check

```bash
# Check all trends exports updated today
gsutil ls -l gs://nba-props-platform-api/v1/trends/*.json | grep "$(date +%Y-%m-%d)"
```

### Verify Export Freshness

```bash
# Check generated_at timestamp for each export
for file in whos-hot-v2 bounce-back what-matters team-tendencies quick-hits deep-dive-current; do
  echo "=== $file ==="
  curl -s "https://storage.googleapis.com/nba-props-platform-api/v1/trends/$file.json" | jq '.generated_at'
done
```

### Check for Errors in Logs

```bash
# If running in Cloud Run, check logs
gcloud logging read "resource.type=cloud_run_revision AND textPayload=~\"trends.*error\"" --limit 50 --format json
```

### BigQuery Cost Monitoring

```bash
# Check BigQuery bytes processed by trends exporters
bq query --use_legacy_sql=false "
SELECT
  user_email,
  job_type,
  total_bytes_processed / POW(10,9) as gb_processed,
  query
FROM \`region-us.INFORMATION_SCHEMA.JOBS\`
WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
  AND query LIKE '%nba_analytics%trends%'
ORDER BY total_bytes_processed DESC
LIMIT 20
"
```

---

## Related Documentation

- **Frontend Implementation:** `/home/naji/code/props-web/docs/06-projects/current/trends-page/`
- **Exporter Source Code:** `data_processors/publishing/*_exporter.py`
- **Publishing Pipeline:** `backfill_jobs/publishing/daily_export.py`
- **Analytics Tables:** `docs/03-schemas/analytics/` (if exists)

---

## Support

For questions or issues:

1. Check this runbook first
2. Review exporter source code for implementation details
3. Verify BigQuery data availability
4. Check GCS permissions and cache headers
5. Escalate to backend team if data pipeline issue

---

**Maintained By:** NBA Platform Team
**Last Verified:** 2025-12-15
