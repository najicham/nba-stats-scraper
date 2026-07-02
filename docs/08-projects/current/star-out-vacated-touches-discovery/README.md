# Star-OUT Vacated-Touches Signal — Discovery

**Status:** Discovery complete. Not yet productionized.
**Discovered:** 2026-05-23
**Cohort size:** N=357 incremental picks over 2024-25 + partial 2025-26
**Expected impact:** ~175 incremental picks/year at 71.7% HR, +35% ROI per bet

---

## TL;DR

When a team's lead scorer (≥18 ppg trailing 30d) is OUT, target teammates ranked 2/3/4 on the team see Vegas lines adjusted UP by +1.73 points. **Books don't fully adjust** — actual scoring still exceeds the adjusted line. Combined with the production model's OVER recommendation at edge ≥ 3, the cohort hits **79.4% OVER across 4 seasons (N=509)**.

**98.3% of qualifying picks are NOT currently captured by the production pipeline** because they're blocked by the OVER edge floor of 6.0. This signal would unlock them as an edge-floor rescue.

## Cohort definition

For each (game_date, team_abbr) where:
1. **Lead scorer** = team's player with highest trailing-30-day ppg (≥5 games on team, ≥18 ppg)
2. Lead scorer is in `nba_raw.nbac_injury_report` latest snapshot with `injury_status = "out"`
3. **Target player** = same team, rank 2-7 by trailing-30-day ppg (rank 5-7 extension validated 2026-05-23 batch 2 — see FINDINGS.md §13)
4. Model recommends OVER (`signed_edge > 0`)
5. Model edge ≥ 3 (bypassing the production OVER floor of 6.0)

## Headline results (4-season validation: 2022-23 through 2026-04)

| Bucket | N | HR following model OVER |
|--------|---|--------------------------|
| edge 3-5 (early injury announce) | 146 | 73.3% |
| edge 3-5 (late ≥17:00 announce) | 78 | 65.4% |
| edge 5+ (early) | 182 | 86.3% |
| edge 5+ (late) | 103 | 86.4% |
| **Combined edge 3+** | **509** | **79.4%** |

ROI at -110 odds: ~+50% per bet on the combined cohort.

## Why this isn't already captured

The production OVER edge floor is **6.0** (raised from 5.0 in Session 522, regime-adaptive). 357/363 qualifying picks fall below that floor and are blocked. The current pipeline has no mechanism to lower the floor based on injury context, so this entire cohort is left on the table.

## Risk flags

- **2025-26 cell weakness:** The validated cells (22-25 + rk3, 25+ + rk4) hit only 47%/52% in 2025-26 vs 55-63% in prior seasons. May reflect the broader 2025-26 model regime issues per [2025-26-anomaly-rootcause.md](../../../09-handoff/...) rather than this signal specifically.
- **N=509 across 4 seasons** is solid but not huge. First live month will be revealing.
- **No live forward-validation yet.** Backtest results often decay live.

## Productionization

**Not yet built.** See [PRODUCTION-PLAN.md](./PRODUCTION-PLAN.md) for the engineering plan, governance gates, and shadow→active criteria.

## Sources

- Discovery session: 2026-05-23
- Full evidence: [FINDINGS.md](./FINDINGS.md)
- Related: Agent 3's vacated-touches finding for assists/rebounds (+0.54 ast spike for 2nd guard when lead-PG out, ~6σ). This doc extends the analog to the points market.
- Auto-memory: `~/.claude/projects/.../memory/star-out-vacated-touches-signal.md`
