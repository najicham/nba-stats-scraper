# Data Sources Documentation

**Created:** 2025-11-30
**Last Updated:** 2025-11-30
**Purpose:** Document raw data sources, coverage, and fallback logic
**Status:** Current

---

## Overview

This directory documents the raw data sources used by the NBA Props Platform, their coverage, and fallback strategies for data resilience.

### Documents

| Document | Purpose |
|----------|---------|
| [`01-coverage-matrix.md`](./01-coverage-matrix.md) | Coverage percentages for all data sources |
| [`02-fallback-strategies.md`](./02-fallback-strategies.md) | Implemented and potential fallback logic |

---

## Quick Reference: Data Source Coverage

### Phase 2 Raw Data Sources

| Data Type | Primary Source | Coverage | Fallback Source | Fallback Coverage |
|-----------|---------------|----------|-----------------|-------------------|
| **Player Props** | `odds_api_player_points_props` | 40% | `bettingpros_player_points_props` | **99.7%** |
| **Game Lines** | `odds_api_game_lines` | 99.1% | None needed | - |
| **Player Boxscores** | `nbac_gamebook_player_stats` | 95%+ | `bdl_player_boxscores` | 98.9% |
| **Team Boxscores** | `nbac_team_boxscore` | 100% | None needed | - |
| **Schedule** | `nbac_schedule` | 100% | None needed | - |
| **Injuries** | `bdl_injuries` | 95%+ | None needed | - |

### Key Insight

**Player props was the CRITICAL gap** - Odds API only has 40% historical coverage, but BettingPros has 99.7%. This fallback was implemented in `upcoming_player_game_context` processor (v3.1).

---

## Related Documentation

- [`data-flow/`](../data-flow/) - Data transformations between phases
- [`dependencies/`](../dependencies/) - Dependency checking logic
- [`processor-registry.md`](../processor-registry.md) - All processors and their sources
