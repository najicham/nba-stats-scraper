# Player Profiles — Project Overview

**Created:** 2026-02-23
**Status:** Research / Design Phase

## Motivation

The prediction system currently treats every player as a bundle of rolling statistics — there is no persistent concept of *who a player is*. A player's recent L5/L10/L20 averages flow through the feature store, but these are ephemeral snapshots that reset with each game. The system has no memory of a player's archetype, tendencies, consistency patterns, or how they tend to interact with the betting market over time.

Adding player profiles would give the model (and the signal/filtering layer) a richer understanding of each player — derived from actual playing style, not unreliable position labels.

## Key Design Decision

**Position labels are unreliable across sites** (NBA.com says "G", ESPN says "PG", BettingPros says "SG", Basketball Reference says "Point Guard"). Rather than scraping and reconciling inconsistent labels, we derive player archetypes entirely from observed playing data:

- Shot zone distribution (paint/mid/3pt rates)
- Scoring volume and efficiency by zone
- Self-creation vs assisted scoring
- Free throw drawing rate
- Rebounding and playmaking tendencies
- Scoring consistency/volatility

Basketball Reference's position labels may serve as a **reference validation** (they tend to be more thoughtful than other sites), but the profile system itself should be data-driven.

## Project Documents

| Document | Purpose |
|----------|---------|
| [01-CURRENT-STATE.md](01-CURRENT-STATE.md) | What player-level data already exists in the system |
| [02-ARCHETYPE-DESIGN.md](02-ARCHETYPE-DESIGN.md) | Proposed archetype classification from playing style |
| [03-PROFILE-SCHEMA.md](03-PROFILE-SCHEMA.md) | What a player profile would contain |
| [04-INTEGRATION-POINTS.md](04-INTEGRATION-POINTS.md) | How profiles connect to predictions, signals, and filtering |
| [05-IMPLEMENTATION-ROADMAP.md](05-IMPLEMENTATION-ROADMAP.md) | Phased build plan |

## Guiding Principles

1. **Derive, don't label** — Archetypes come from play data, not scraped position strings
2. **Start with what we have** — Most of the raw data already exists in BigQuery
3. **Prove value before building** — Run offline analysis first to confirm profiles improve predictions
4. **Profiles inform, model decides** — Profiles are features/filters, not overrides to the ML model
