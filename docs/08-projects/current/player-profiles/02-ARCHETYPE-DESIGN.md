# Player Profiles — Archetype Design

## Philosophy: Derive, Don't Label

Position labels across sites are inconsistent and often meaningless for modern NBA basketball. Nikola Jokic is labeled "C" but functions as a point guard. LeBron James is "F" but handles the ball more than most guards. Shai Gilgeous-Alexander is "G" but scores primarily in the paint.

Instead of reconciling contradictory labels, we classify players by **what they actually do on the court**.

## Archetype Dimensions

A player profile isn't a single label — it's a multi-dimensional characterization. Each dimension is derived from `player_game_summary` data aggregated over a rolling window (suggested: 20 games, with season-level as a stability reference).

### Dimension 1: Scoring Zone Profile

Where a player gets their points. Derived from `paint_rate`, `mid_range_rate`, `three_pt_rate`.

| Archetype | Criteria | Examples |
|-----------|----------|----------|
| **Interior Scorer** | paint_rate >= 45% | Giannis, Zion, most traditional centers |
| **Perimeter Scorer** | three_pt_rate >= 45% | Steph Curry, Klay Thompson, Buddy Hield |
| **Mid-Range Scorer** | mid_range_rate >= 30% AND not interior/perimeter | DeMar DeRozan, KD, Kawhi |
| **Balanced Scorer** | No zone dominates | LeBron, Jayson Tatum |

This already exists as `primary_scoring_zone` in Phase 4, but the thresholds should be tuned and the classification should be stored as a profile property rather than recomputed daily.

### Dimension 2: Shot Creation

How a player gets their looks. Derived from `assisted_rate` and `unassisted_rate`.

| Archetype | Criteria | Description |
|-----------|----------|-------------|
| **Self-Creator** | unassisted_rate >= 55% | Creates own shot; less dependent on teammates |
| **Catch-and-Shoot** | assisted_rate >= 70% | Highly dependent on teammates for looks |
| **Mixed Creator** | Neither extreme | Combination |

**Why this matters for betting:** Self-creators are more predictable — their scoring is less affected by lineup changes, teammate injuries, or game flow. Catch-and-shoot players are more volatile because their production depends on the team creating looks for them.

### Dimension 3: Free Throw Drawing (Paint Pressure)

How much a player gets to the line. Derived from `ft_attempts / fg_attempts` (FT rate).

| Category | FT Rate | Description |
|----------|---------|-------------|
| **High FT Drawer** | FTr >= 0.40 | Physical player, drives and draws contact |
| **Moderate FT Drawer** | 0.25 <= FTr < 0.40 | Average |
| **Low FT Drawer** | FTr < 0.25 | Jump shooter, rarely gets to the line |

**Why this matters for betting:** FT drawing is one of the most stable per-game scoring components. Players with high FT rates have a scoring floor — they get points even on bad shooting nights. This directly affects over/under consistency.

### Dimension 4: Scoring Consistency

How predictable a player's output is. Derived from coefficient of variation (CV = std / mean) and over/under tendencies.

| Category | CV | Description |
|----------|------|-------------|
| **Metronome** | CV < 0.20 | Very consistent, tight distribution around mean |
| **Normal** | 0.20 <= CV < 0.35 | Typical variance |
| **Volatile** | CV >= 0.35 | Boom-or-bust, wide distribution |

Additional consistency metrics:
- **Over rate at line**: % of recent games going over their typical prop line
- **Bust rate**: % of games scoring < 60% of season average
- **Boom rate**: % of games scoring > 140% of season average

**Why this matters for betting:** Volatile players need higher edge to be confident. A 3-point edge on a metronome is much safer than a 3-point edge on a volatile scorer.

### Dimension 5: Usage Tier

How central a player is to their team's offense. Derived from `usage_rate` and `minutes_played`.

| Category | Criteria | Description |
|----------|----------|-------------|
| **Primary Option** | USG >= 28% AND mins >= 32 | Team's go-to scorer |
| **Secondary Option** | 22% <= USG < 28% AND mins >= 28 | Significant contributor |
| **Role Player** | 18% <= USG < 22% | Defined role, moderate volume |
| **Low Usage** | USG < 18% | Specialist or limited role |

This is more meaningful than the current line-value-based tier (star/starter/role/bench) because it's derived from actual usage data, not the betting market's assessment.

### Dimension 6: Playmaking Profile (Future)

How much a player distributes vs scores. Derived from `assists`, `turnovers`, and `usage_rate`.

| Category | AST/TO Ratio | Description |
|----------|-------------|-------------|
| **Primary Playmaker** | AST >= 6 per game, AST/TO >= 2.5 | Floor general |
| **Secondary Playmaker** | 3 <= AST < 6, AST/TO >= 2.0 | Creates for others sometimes |
| **Non-Playmaker** | AST < 3 | Pure scorer or role player |

**Relevance:** Playmakers often have more consistent scoring because they control pace and can choose when to score. Also relevant for assists props if we expand beyond points.

## Composite Archetype Labels

Combining dimensions creates a rich archetype string. Examples:

| Player Type | Zone | Creation | FT | Consistency | Usage |
|-------------|------|----------|----|-------------|-------|
| **Paint Bully** | Interior | Self-Creator | High FT | Normal | Primary |
| **Sniper** | Perimeter | Catch-and-Shoot | Low FT | Normal | Role |
| **Shot Creator** | Balanced | Self-Creator | Moderate FT | Volatile | Primary |
| **Efficient Big** | Interior | Mixed | High FT | Metronome | Secondary |
| **3-and-D** | Perimeter | Catch-and-Shoot | Low FT | Volatile | Low Usage |

These are descriptive labels for human readability. The model would consume the underlying continuous values, not categorical labels.

## What About Basketball Reference Position Labels?

Basketball Reference tends to be more thoughtful with position labeling than NBA.com or ESPN. Their data could be useful as a **validation cross-reference**, not a primary input:

- Compare our derived archetypes against BRef positions to sanity-check
- Use BRef's PG/SG/SF/PF/C labels (5-position, not 3) as a supplementary categorical feature
- The existing `bref_player_boxscores` scraper could be extended to pull position from player pages

However, even BRef positions are static labels that don't capture how a player actually plays. A data-derived archetype will always be more accurate for prediction purposes.

## Archetype Stability

Some dimensions are very stable (shot zone profile changes slowly), while others shift with circumstance:

| Dimension | Stability | Update Frequency |
|-----------|-----------|-----------------|
| Scoring zone | Very stable | Weekly or on structural change |
| Shot creation | Stable | Weekly |
| FT drawing | Very stable | Weekly |
| Consistency | Moderately stable | Every 10 games |
| Usage tier | Can shift (injuries, trades) | Daily (detect via structural change) |

The profile should have both a **season baseline** and a **rolling current** version to detect when a player's role has changed.
