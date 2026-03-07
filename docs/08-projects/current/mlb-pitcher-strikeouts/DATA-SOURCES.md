# MLB Data Sources — Current State & Gaps

**Updated:** 2026-03-07
**Status:** BDL retired. MLB Stats API is primary. Key gaps: weather, umpires, lineup confirmation.

---

## Active Sources (Working)

| Source | Table | Records | Coverage | Notes |
|--------|-------|---------|----------|-------|
| **MLB Stats API** | `mlb_pitcher_stats` | 42,125 | 2024-03 → 2025-09 | Primary pitcher stats. Replaces BDL. |
| **MLB Stats API** | `mlbapi_batter_stats` | Backfilling | 2024-03 → 2025-09 | Replaces BDL. Proper game_pk granularity. |
| **MLB Stats API** | `mlb_schedule` | 9,881 | All seasons | Game schedule, status, venue. |
| **MLB Stats API** | `mlb_game_lineups` | 10,319 | 2024-2025 | Starting lineups (pitcher + batters). |
| **MLB Stats API** | `mlb_lineup_batters` | 185,418 | 2024-2025 | Individual batter lineup positions. |
| **BettingPros** | `bp_pitcher_props` | 25,404 | 2022-04 → 2025-09 | K prop lines + projections. **Critical for model.** |
| **Odds API** | `oddsa_pitcher_props` | 60,589 | 2024-04 → 2025-09 | Multi-book K lines (odds, over/under). |
| **Odds API** | `oddsa_batter_props` | 635,497 | 2024-2025 | Batter props (not used in K model yet). |
| **Statcast** (pybaseball) | `statcast_pitcher_game_stats` | 39,918 | 2024-2025 | Rolling SwStr%, velocity, spin (analytics layer). |
| **Statcast** (pybaseball) | `statcast_pitcher_daily` | 1,506 | Backfilling | Raw daily pitch-level aggregates. |
| **FanGraphs** | `fangraphs_pitcher_season_stats` | 1,704 | Latest snapshot | Season-level SwStr%, CSW%, K%, contact%. |
| **BettingPros** | `bp_batter_props` | 775,818 | 2024-2025 | Batter K props (for bottom-up model). |

## Retired Sources (BDL — Cancel Subscription)

See `BDL-RETIREMENT-PLAN.md` for details.

| Table | Rows | Issue |
|-------|------|-------|
| `bdl_pitcher_stats` | 15 | Dead — migrated to MLB Stats API |
| `bdl_batter_stats` | 97K | No game_id granularity — all rows have `game_id = "DATE_UNK_UNK"` |
| `bdl_injuries` | 222 | Single snapshot from Jan 15, 2026 — useless |
| 24 other bdl_* tables | 0 | Never populated |

---

## Data Gaps — What We Need

### Gap 1: Injuries / IL Status (Priority: LOW)
**Why low:** Pitchers on the IL won't have prop lines from bookmakers. The Odds API already filters them out naturally. The IL query in `base_predictor.py` is defense-in-depth.

**If we want it anyway:**
- MLB Stats API: `https://statsapi.mlb.com/api/v1/transactions?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD`
- Free, no auth. Contains IL placements (typeCode='IL'), activations, DFA.
- Effort: ~2 hours for scraper + processor.

### Gap 2: Umpire Assignments (Priority: MEDIUM)
**Why it matters:** Home plate umpire K tendencies vary significantly. Some umpires have wider/tighter strike zones. Walk-forward showed +2-3pp HR improvement with umpire context in NBA (covers_referee_stats).

**Source options:**
- MLB Stats API: `https://statsapi.mlb.com/api/v1/schedule?date=YYYY-MM-DD&sportId=1&hydrate=officials`
- Returns umpire crew for each game. `officials` array includes home plate umpire.
- Cross-reference with umpire K-rate historical data from Statcast/Savant.
- Table `umpire_game_assignment` already exists (empty). Schema ready.

**Effort:** ~3 hours (scraper + historical K-rate lookup table).

### Gap 3: Weather (Priority: MEDIUM)
**Why it matters:** Temperature, wind, humidity affect ball flight and pitcher grip. Cold weather = more swings and misses (slippery bats) = more K's. Dome stadiums = controlled environment.

**Source options:**
- Open-Meteo API: `https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,wind_speed_10m`
- Free, no auth, cloud-friendly.
- Need venue → lat/lon mapping (30 stadiums, static).
- Table `game_weather` already exists (empty). Schema ready.

**Effort:** ~3 hours (venue mapping + scraper + processor).

### Gap 4: Game Lines / Run Totals (Priority: LOW-MEDIUM)
**Why it matters:** Over/under run totals correlate with K's. High-total games = more offense = fewer K's. Low-total games = pitching duels = more K's.

**Source:** Already have Odds API configured. Just need to enable the `baseball_mlb` sport for game lines (currently only fetching player props).
- Table `oddsa_game_lines` exists (empty).

**Effort:** ~1 hour (add sport to existing Odds API scraper config).

### Gap 5: Pitch Mix / Arsenal Data (Priority: LOW)
**Why it matters:** Pitchers with high slider/curveball usage K more. Changes in pitch mix game-to-game predict K variance.

**Source:** Statcast via pybaseball. We already scrape aggregate SwStr% but not per-pitch-type breakdowns.

**Effort:** ~2 hours (extend statcast scraper, add pitch-type columns).

---

## Recommended Priority Order

1. **Umpire assignments** — highest signal-to-effort ratio. MLB Stats API hydrate is trivial. Umpire K-rates have real predictive power.
2. **Game lines (run totals)** — 1 hour to enable. Provides game-environment context.
3. **Weather** — free API, schemas exist. Meaningful for outdoor stadiums (21 of 30).
4. **Injuries** — low priority since prop lines already filter IL pitchers.
5. **Pitch mix** — nice-to-have, Statcast extension.

---

## API Summary

| API | Auth | Rate Limit | Cloud-OK | Cost |
|-----|------|-----------|----------|------|
| MLB Stats API | None | Generous (~100/min) | Yes | Free |
| Odds API | API key (have it) | 500/month free tier | Yes | $0 (free tier) or $79/mo |
| Statcast (pybaseball) | None | ~1 req/2sec | Yes | Free |
| BettingPros | Web scrape | Careful | Yes | Free |
| FanGraphs | Web scrape | Careful | Yes | Free |
| Open-Meteo | None | Unlimited | Yes | Free |
| ~~BDL~~ | ~~API key~~ | — | — | **CANCELLED** (Session 430) |
