# Trends v2 Exporters Project

**Status:** ✅ COMPLETE
**Created:** 2024-12-14
**Completed:** 2024-12-15
**Priority:** High

---

## Overview

Build 6 new JSON exporters to power the Trends v2 page on the props website. These exporters generate pre-computed analytics that highlight betting patterns, player trends, and situational factors.

**Key Change from v1:** Hit rate (prop betting success) is the primary metric, not raw scoring averages.

---

## Sections to Build

| Section | File | Refresh | Priority |
|---------|------|---------|----------|
| Who's Hot/Cold | `whos-hot-v2.json` | Daily 6 AM | Critical |
| Bounce-Back Watch | `bounce-back.json` | Daily 6 AM | High |
| What Matters Most | `what-matters.json` | Weekly Mon 6 AM | High |
| Team Tendencies | `team-tendencies.json` | Bi-weekly Mon 6 AM | High |
| Quick Hits | `quick-hits.json` | Weekly Wed 8 AM | Medium |
| Deep Dive Promo | `deep-dive-current.json` | Monthly | Low |

---

## Data Sources (All Confirmed Available)

| Data | Source Table |
|------|--------------|
| Historical prop lines | `nba_raw.bettingpros_player_points_props` |
| Player game logs | `nba_analytics.player_game_summary` |
| Player shot profiles | `nba_precompute.player_shot_zone_analysis` |
| Team defense by zone | `nba_precompute.team_defense_zone_analysis` |
| Pace data | `nba_analytics.team_offense_game_summary` |
| Player registry | `nba_reference.nba_players_registry` |

---

## Key Concepts

### Hit Rate Calculation
```sql
-- Join prop lines with actuals to calculate hit rate
SELECT
  player_lookup,
  COUNT(*) as games,
  SUM(CASE WHEN actual_points > prop_line THEN 1 ELSE 0 END) as overs_hit,
  overs_hit / games as hit_rate
FROM props_with_actuals
```

### Archetype Classification (using years-in-league)
```sql
CASE
  WHEN years_in_league >= 10 AND usage_rate >= 0.25 AND ppg >= 20 THEN 'veteran_star'
  WHEN years_in_league BETWEEN 5 AND 9 AND usage_rate >= 0.28 AND ppg >= 22 THEN 'prime_star'
  WHEN years_in_league < 5 AND usage_rate >= 0.22 AND ppg >= 18 THEN 'young_star'
  ELSE 'role_player'
END
```

### Shot Profile Classification
```sql
CASE
  WHEN paint_rate_last_10 >= 0.50 THEN 'interior'
  WHEN three_pt_rate_last_10 >= 0.50 THEN 'perimeter'
  WHEN mid_range_rate_last_10 >= 0.30 THEN 'mid_range'
  ELSE 'balanced'
END
```

---

## Output Location

All files export to:
```
gs://nba-props-platform-api/v1/trends/
├── whos-hot-v2.json
├── bounce-back.json
├── what-matters.json
├── team-tendencies.json
├── quick-hits.json
└── deep-dive-current.json
```

---

## Related Documents

- **Requirements Spec:** `/home/naji/code/props-web/docs/06-projects/current/trends-page/backend-data-requirements.md`
- **Data Available:** `/home/naji/code/props-web/docs/06-projects/current/trends-page/backend-data-available.md`
- **Shot Profile Exploration:** `/home/naji/code/props-web/docs/06-projects/current/trends-page/shot-profile-data-exploration.md`

---

## Success Criteria

- [ ] All 6 exporters generate valid JSON
- [ ] Unit tests pass with >90% coverage
- [ ] Integration tests verify GCS uploads
- [ ] Refresh schedules configured in Cloud Scheduler
- [ ] Frontend can consume all endpoints
- [ ] Performance: Each exporter completes in <60 seconds
