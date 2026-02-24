# Player Profiles — Integration Points

## How Profiles Connect to the Prediction System

Player profiles would integrate at four levels: ML features, signal filtering, best bets selection, and monitoring/analysis.

---

## 1. ML Feature Vector Integration

### Dead Feature Slots (Reserved, Do Not Replace)

Four features in V12 always emit defaults. These are kept as reserves for future use — do NOT replace them with profile features. Instead, add profile features as **new** feature indices beyond the current 54.

| Index | Current (Dead) | Status |
|-------|----------------|--------|
| 41 | `spread_magnitude` (always 5.0) | RESERVED |
| 42 | `implied_team_total` (always 112.0) | RESERVED |
| 47 | `teammate_usage_available` (always 0.0) | RESERVED |
| 50 | `multi_book_line_std` (always 0.5) | RESERVED |

### Add New Features (Next Feature Expansion)

If we go beyond 54 features in a V13+ model:

| Candidate Feature | Source | Rationale |
|-------------------|--------|-----------|
| `ft_rate_season` | profile | FT drawing is a scoring floor signal |
| `points_cv_season` | profile | Volatile players need higher edge |
| `assisted_rate_season` | profile | Self-creators are more predictable |
| `scoring_floor` | profile | 10th percentile output = downside risk |
| `over_rate_season` | profile | Some players consistently beat their averages |
| `bust_rate_season` | profile | How often a player completely underperforms |

### Encoding Strategy for Archetypes

CatBoost handles categorical features natively. Archetype labels can be fed directly:

```python
# CatBoost can use these as categorical features
cat_features = ['scoring_zone_archetype', 'creation_archetype',
                'consistency_archetype', 'usage_archetype']
```

Alternatively, use the continuous underlying values (paint_rate, CV, assisted_rate) and let CatBoost learn the boundaries. **Recommendation: use continuous values** — they carry more information than bucketized labels, and CatBoost excels at finding optimal splits.

---

## 2. Signal System Integration

### Consistency-Aware Edge Filtering

Currently, edge >= 3 is a flat filter for all players. With profiles:

```
metronome player + edge 3 → confident (their output is predictable)
volatile player + edge 3  → less confident (their output swings wildly)
```

**Implementation:** Adjust effective edge threshold by consistency archetype:
- Metronome: edge >= 3 (unchanged)
- Normal: edge >= 3 (unchanged)
- Volatile: edge >= 4 or edge >= 5 (require more cushion)

### Self-Creator Signal

Self-creators are less affected by teammate injuries and lineup changes. When a star teammate is out:

```
catch_and_shoot player + star_out → CAUTION (their looks may dry up)
self_creator + star_out           → NEUTRAL or SLIGHT BOOST (more touches)
```

This could enhance the existing `star_teammates_out` feature (index 37) with creation-context.

### FT Floor Signal

Players with high FT drawing rates have a scoring floor even on bad shooting nights. Could be a positive signal for OVER bets at lower lines:

```
high_ft_drawer + OVER + line <= 20 → positive signal (FTs provide a floor)
low_ft_drawer + OVER               → neutral (no safety net)
```

### Bench UNDER Enhancement

The existing `bench_under` signal (76.9% HR) could be refined:

```
bench + UNDER + volatile player → stronger signal (high bust rate)
bench + UNDER + metronome       → weaker signal (consistent even in limited role)
```

---

## 3. Best Bets Selection Integration

### Player Difficulty Rating

The blacklist currently uses a flat 40% HR threshold. With profiles, we can be smarter:

| Player Type | Prediction Difficulty | Action |
|-------------|----------------------|--------|
| Metronome + self-creator | Easy | Include with standard edge |
| Normal + mixed creator | Normal | Standard filtering |
| Volatile + catch-and-shoot | Hard | Require higher edge or exclude |

This replaces the binary blacklist with a continuous difficulty score.

### Direction-Aware Filtering

Combine profile with bet direction:

```
high_ft_drawer + OVER  → boost (FT floor protects the over)
high_ft_drawer + UNDER → caution (hard to go under when player draws FTs)
volatile + OVER        → risky (could boom, but bust rate is high)
volatile + UNDER       → interesting (bust rate is high, but boom rate is too)
```

### Pick Angle Enhancement

`pick_angle_builder.py` currently generates human-readable reasoning. Profiles would add richer angles:

```
Current: "Star player, strong edge of 6.2"
Enhanced: "Interior scorer, self-creator with metronome consistency.
           FT rate provides scoring floor of 18.5. Edge 6.2."
```

---

## 4. Monitoring and Analysis Integration

### Subset Performance by Archetype

Add archetype-based subsets to the dynamic subset system:

| Subset | Definition | Purpose |
|--------|-----------|---------|
| `interior_scorers` | `scoring_zone_archetype = 'interior'` | Track if model predicts interior scorers well |
| `perimeter_scorers` | `scoring_zone_archetype = 'perimeter'` | Track 3PT-dependent player prediction quality |
| `self_creators` | `creation_archetype = 'self_creator'` | Validate self-creator hypothesis |
| `volatile_players` | `consistency_archetype = 'volatile'` | Monitor high-variance prediction quality |
| `high_ft_drawers` | `ft_drawing_archetype = 'high'` | Validate FT floor hypothesis |

### Profile Drift Detection

When a player's profile shifts significantly (trade, injury return, role change), flag it:

```
Player X: usage_archetype changed from 'secondary' → 'primary' (star teammate injured)
Action: Model predictions may be less reliable during transition period
```

---

## 5. What NOT to Integrate

Avoid these integration pitfalls:

| Bad Idea | Why |
|----------|-----|
| Override model predictions with profile rules | Profiles inform, model decides |
| Block all volatile players | Volatility cuts both ways — model already accounts for some of it |
| Use archetype labels as hard filters | Use continuous values; let CatBoost learn thresholds |
| Build complex interaction features | Keep it simple; CatBoost handles interactions natively |
| Weight predictions by profile confidence | Let the zero-tolerance system handle data quality |
