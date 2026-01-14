# Copy-Paste This to New Chat

```
Continue MLB pitcher strikeouts implementation - V1/V2 features.

READ THESE DOCS FIRST:
1. docs/09-handoff/2026-01-07-MLB-V1-V2-IMPLEMENTATION-HANDOFF.md (implementation guide)
2. docs/08-projects/current/mlb-pitcher-strikeouts/ULTRATHINK-MLB-SPECIFIC-ARCHITECTURE.md (architecture rationale)

PROJECT CONTEXT:
- Building MLB pitcher strikeout prediction system
- Already have: 28 scrapers, 22 raw tables, 2 analytics tables, 25-feature processor
- Key insight: MLB can use "bottom-up model" - sum individual batter K rates since we KNOW the lineup

WHAT TO IMPLEMENT:

V1 (MUST HAVE):
1. Create `mlb_precompute.lineup_k_analysis` table - stores per-game lineup K calculation
2. Create `mlb_raw.umpire_game_assignment` table - umpire strike zone tendencies
3. Create `mlb_precompute.pitcher_innings_projection` table - expected IP
4. Create lineup_k_analysis_processor.py
5. Add features f25-f29 to pitcher_features_processor.py:
   - f25: bottom_up_k_expected (THE KEY - sum of batter K probs)
   - f26: lineup_k_vs_hand (lineup K rate vs pitcher handedness)
   - f27: platoon_advantage (LHP vs RHH lineup)
   - f28: umpire_k_factor
   - f29: projected_innings

V2 (SHOULD HAVE):
6. Create `mlb_precompute.pitcher_arsenal_summary` table - whiff rates, velocity from Statcast
7. Create `mlb_precompute.batter_k_profile` table - platoon splits, K vulnerability
8. Add features f30-f34:
   - f30: velocity_trend
   - f31: whiff_rate
   - f32: put_away_rate
   - f33: lineup_weak_spots
   - f34: matchup_edge

EXISTING CODE TO MODIFY:
- data_processors/precompute/mlb/pitcher_features_processor.py (add new features)
- Already has bottom_up_k calculation at line 512-543 - just need to expose it as f25

START BY:
1. Reading the handoff doc for full table schemas
2. Creating the BigQuery tables
3. Creating lineup_k_analysis_processor.py
4. Updating pitcher_features_processor.py with f25-f34

The goal is expanding from 25 features to 35 features with MLB-specific data.
```
