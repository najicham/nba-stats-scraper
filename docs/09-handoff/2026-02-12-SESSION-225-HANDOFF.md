# Session 225 Handoff — Player Modal Data Enrichment

## What Was Done

Fixed the player detail endpoint (`/v1/tonight/player/{lookup}.json`) to populate fields the frontend was already built to consume. The player modal on playerprops.io was rendering sparse because several API fields were null, hardcoded, or mis-serialized.

### Changes (1 commit, 1 file + tests)

**File:** `data_processors/publishing/tonight_player_exporter.py`

| Fix | Problem | Solution |
|-----|---------|----------|
| `opponent_defense` | null — data existed in Phase 4 but wasn't surfaced | Added `_format_opponent_defense()` mapping `team_defense_zone_analysis` → `{rating, rank, position_ppg_allowed, position_ppg_rank}` |
| `days_rest` | null when UPCG table didn't have it | Compute fallback from `recent_form[0].game_date` (date diff to target) |
| `fatigue.context` | JSON string instead of object (`"{\"days_rest\": 0}"`) | Added `json.loads()` on `fatigue_context_json` when it's a string |
| `line_movement` | null — data existed in UPCG but wasn't surfaced | Added `_format_line_movement()` → `{opened, current, movement, favorable}` |

### Coverage Notes

- **opponent_defense**: ~100% coverage (defense tier computed nightly for all 30 teams). `position_ppg_allowed` and `position_ppg_rank` are null — we only track team-level defense, not position-level.
- **line_movement**: ~33% of players have opening line data (Odds API/BettingPros). Returns null for the rest. Frontend hides the card when null.
- **days_rest**: Will now always populate if the player has any prior game in `player_game_summary`.
- **fatigue.context**: Fixed serialization bug. No data coverage change.

### Tests

Added 8 new tests in `tests/unit/publishing/test_tonight_player_exporter.py`:
- `test_json_has_opponent_defense_from_tier`
- `test_days_rest_fallback_from_recent_form`
- `test_fatigue_context_json_string_parsed`
- `test_fatigue_context_already_dict`
- `test_line_movement_with_data`
- `test_line_movement_unfavorable`
- `test_line_movement_null_when_no_opening`
- `test_line_movement_no_movement`

All 21 tests pass. 3 pre-existing `TestSafeFloat` failures are unrelated (test calls `exporter._safe_float` but `safe_float` is a standalone function in `exporter_utils`).

## Deployment

- Pushed to main → Cloud Build auto-deploys Phase 6 export function
- New JSON files will generate on next pipeline run (today's games)
- No manual deploy needed

## Open Items (P1 — Future Sessions)

### prediction_text / prediction_text_premium
AI-generated analysis paragraphs. No text generation infrastructure exists today. Options:
- **Template-based** (f-strings from `tonights_factors`): 1-2 sessions, deterministic, no API cost
- **LLM-generated** (Claude API): 2-3 sessions, natural language, ~$0.01/player, adds 10+ min to export
- **Hybrid** (templates for free, LLM for premium): best balance

Recommendation: start with templates for `prediction_text`, evaluate LLM for premium later.

### matchup_grade
Letter grade (A-F) from defense tier + vs_opponent splits. Trivial — 15 min. Can tack onto any session.

### position_ppg_allowed / position_ppg_rank
Requires new Phase 3/4 processor to track defensive stats by opposing player position. Currently only team-level aggregates exist. Separate project.

### line_movement coverage improvement
Opening line coverage is ~33% because we often only have one snapshot. Options:
- Scrape earlier in the day to capture opening lines before they move
- Use BettingPros `opening_line` field more aggressively (already in raw table)
- Add a morning snapshot to Odds API scraper schedule

## Key Files

| File | Purpose |
|------|---------|
| `data_processors/publishing/tonight_player_exporter.py` | Player detail JSON generation (modified) |
| `tests/unit/publishing/test_tonight_player_exporter.py` | Unit tests (modified) |
| `data_processors/analytics/upcoming_player_game_context/betting_data.py` | Where opening/current lines are computed upstream |
| `schemas/bigquery/precompute/team_defense_zone_analysis.sql` | Source of opponent defense data |
