# Orchestration Parameter Fixes Summary

**Date:** 2025-11-13
**Issue:** Orchestration system was passing incorrect parameters to scrapers
**Status:** ✅ Fixed (with Phase 2 TODOs noted)

---

## Overview

Verified orchestration system parameters against documented scraper requirements and fixed 12 parameter mismatches.

---

## Files Modified

1. **`config/scraper_parameters.yaml`** - Corrected parameter definitions
2. **`orchestration/parameter_resolver.py`** - Added 5 new complex resolvers
3. **`bin/orchestration/verify_parameters.py`** - Created verification script

---

## Issues Fixed

### **1. Scrapers Receiving Unnecessary Parameters** ✅ FIXED

**nbac_player_list**
- ❌ Was receiving: `season`
- ✅ Now receives: Empty dict `{}`
- **Reason:** Scraper auto-fetches current season, no parameters needed

**bdl_standings**
- ❌ Was receiving: `season`, `date`
- ✅ Now receives: Empty dict `{}`
- **Reason:** Scraper auto-fetches current standings, no parameters needed

**bdl_active_players**
- ❌ Was receiving: `season`
- ✅ Now receives: Empty dict `{}`
- **Reason:** Scraper auto-fetches active players, no parameters needed

### **2. Scrapers Receiving Wrong Parameters** ✅ FIXED

**bdl_box_scores**
- ❌ Was receiving: `season`, `date`
- ✅ Now receives: `date` only
- **Reason:** Scraper only needs date, not season

**nbac_referee_assignments**
- ❌ Was receiving: Empty dict
- ✅ Now receives: `date`
- **Reason:** Scraper requires date parameter (YYYY-MM-DD format)

**nbac_injury_report**
- ❌ Was receiving: Empty dict
- ✅ Now receives: `gamedate`
- **Note:** Scraper actually needs `gamedate` + `hour` + `period`, but hour/period need time-based resolver
- **TODO:** Add time-based resolver for hour/period in Phase 2

### **3. Complex Scrapers Moved to Proper Category** ✅ FIXED

**br_season_roster**
- ❌ Was in: `simple_scrapers` with `season` parameter
- ✅ Now in: `complex_scrapers` with custom resolver
- **Reason:** Needs `teamAbbr` + `year` (ending year), must iterate over all 30 teams
- **Phase 1:** Returns LAL only
- **TODO Phase 2:** Iterate over all 30 teams

**nbac_gamebook_pdf**
- ❌ Was in: `simple_scrapers` with `season` + `date`
- ✅ Now in: `complex_scrapers` with custom resolver
- **Reason:** Needs `game_code` in format "YYYYMMDD/AWYHOM"
- **Phase 1:** Returns first game only
- **TODO Phase 2:** Iterate over all games

**oddsa_player_props**
- ❌ Was in: `simple_scrapers` with `sport` + `game_date`
- ✅ Now in: `complex_scrapers` with custom resolver
- **Reason:** Needs `event_id` from oddsa_events scraper
- **Phase 1:** Returns `sport` + `game_date` with warning
- **TODO Phase 2:** Fetch event_ids from oddsa_events results in BigQuery

**oddsa_game_lines**
- ❌ Was in: `simple_scrapers` with `sport` + `game_date`
- ✅ Now in: `complex_scrapers` with custom resolver
- **Reason:** Needs `event_id` from oddsa_events scraper
- **Phase 1:** Returns `sport` + `game_date` with warning
- **TODO Phase 2:** Fetch event_ids from oddsa_events results in BigQuery

### **4. New Complex Resolvers Added** ✅ IMPLEMENTED

Added 5 new resolvers to `parameter_resolver.py`:

1. **`_resolve_game_specific_with_game_date()`**
   - For: `nbac_team_boxscore`
   - Returns: `game_id`, `game_date` (YYYY-MM-DD format with dashes)
   - Note: Different from `_resolve_game_specific()` which uses `gamedate` (no dashes)

2. **`_resolve_br_season_roster()`**
   - For: `br_season_roster`
   - Returns: `teamAbbr` (3-letter code), `year` (ending year)
   - Phase 1: Returns LAL only
   - Phase 2 TODO: Iterate over all 30 teams

3. **`_resolve_nbac_gamebook_pdf()`**
   - For: `nbac_gamebook_pdf`
   - Returns: `game_code` (format: "YYYYMMDD/AWYHOM")
   - Phase 1: Returns first game only
   - Phase 2 TODO: Iterate over all games

4. **`_resolve_odds_props()`**
   - For: `oddsa_player_props`
   - Returns: `sport`, `game_date` (with warning)
   - Phase 2 TODO: Add `event_id` from oddsa_events BigQuery results

5. **`_resolve_odds_game_lines()`**
   - For: `oddsa_game_lines`
   - Returns: `sport`, `game_date` (with warning)
   - Phase 2 TODO: Add `event_id` from oddsa_events BigQuery results

---

## Verification

### **Verification Script Created**

**Location:** `bin/orchestration/verify_parameters.py`

**Usage:**
```bash
# Verify all scrapers
python bin/orchestration/verify_parameters.py

# Verify specific scraper
python bin/orchestration/verify_parameters.py --scraper nbac_schedule_api

# Verbose mode
python bin/orchestration/verify_parameters.py --verbose
```

**Features:**
- Compares resolved parameters against documented requirements
- Checks for missing required parameters
- Detects unexpected parameters
- Provides detailed output with format notes
- Exit code 0 if all pass, 1 if failures/errors

---

## Phase 2 TODOs

### **High Priority**

1. **Event ID Resolution for Odds API Scrapers**
   - Scrapers: `oddsa_player_props`, `oddsa_game_lines`
   - Current: Returns `sport` + `game_date` only
   - Needed: Fetch `event_id` from `oddsa_events` scraper results in BigQuery
   - Impact: These scrapers will fail without event_id
   - **Solution:** Add resolver that queries BigQuery for event_ids from latest oddsa_events run

2. **Time-Based Resolution for Injury Report**
   - Scraper: `nbac_injury_report`
   - Current: Returns `gamedate` only
   - Needed: `hour` (1-12) + `period` ("AM"/"PM")
   - Impact: Scraper will fail without hour/period
   - **Solution:** Add time-based resolver that uses current hour (or configurable time window)

### **Medium Priority**

3. **Team Iteration for Basketball Reference**
   - Scraper: `br_season_roster`
   - Current: Returns LAL only
   - Needed: Iterate over all 30 NBA teams
   - Impact: Only getting LAL roster data
   - **Solution:** Return list of parameter sets (one per team) and update workflow executor to handle lists

4. **Game Iteration for Game-Specific Scrapers**
   - Scrapers: All game-specific scrapers (nbac_play_by_play, nbac_team_boxscore, etc.)
   - Current: Returns first game only
   - Needed: Iterate over all games today
   - Impact: Only processing first game
   - **Solution:** Return list of parameter sets (one per game) and update workflow executor to handle lists

### **Low Priority**

5. **Season Format Verification**
   - Check if season format `"2024-25"` works for all scrapers
   - Some scrapers may need `"2025"` (4-digit year) instead
   - Test with actual scraper calls

---

## Testing Recommendations

### **1. Run Verification Script**

```bash
# Test all scrapers
python bin/orchestration/verify_parameters.py

# Expected output: Should show which scrapers pass/fail parameter checks
```

### **2. Dry-Run Workflow Executor**

```bash
# Test parameter resolution in context
python orchestration/workflow_executor.py --dry-run

# Should show resolved parameters for each scraper without calling them
```

### **3. Test Individual Scraper Resolution**

```python
from orchestration.parameter_resolver import ParameterResolver

resolver = ParameterResolver()
context = resolver.build_workflow_context('test_workflow')

# Test specific scraper
params = resolver.resolve_parameters('nbac_schedule_api', context)
print(params)  # Should show: {'season': '2024-25'}

params = resolver.resolve_parameters('bdl_standings', context)
print(params)  # Should show: {}

params = resolver.resolve_parameters('nbac_referee_assignments', context)
print(params)  # Should show: {'date': '2025-11-13'}
```

---

## Breaking Changes

### **Workflow Configuration Updates Needed**

If workflows.yaml references `br_season_roster`, `nbac_gamebook_pdf`, `oddsa_player_props`, or `oddsa_game_lines`:

- ✅ **No changes needed** - They're now handled as complex scrapers
- ⚠️ **Phase 2 Impact:** These scrapers will log warnings in Phase 1 (oddsa scrapers) or only process first item (br_season_roster, gamebook)

### **Scraper Service Updates Needed**

None - all changes are in orchestration layer only

---

## Success Criteria

✅ **Phase 1 Complete:**
- All simple parameter mappings corrected
- Complex resolvers implemented for basic cases
- Verification script created
- Documentation updated

⏳ **Phase 2 Goals:**
- Event ID resolution working for Odds API
- Time-based resolution for injury report
- Full team iteration for Basketball Reference
- Full game iteration for game-specific scrapers

---

## Related Documentation

- **Parameter Formats Reference:** `docs/reference/scrapers/2025-11-13-parameter-formats.md`
- **Orchestration Guide:** `docs/orchestration/phase1_monitoring_operations_guide.md`
- **Scraper Parameters Config:** `config/scraper_parameters.yaml`
- **Parameter Resolver:** `orchestration/parameter_resolver.py`

---

**Last Updated:** 2025-11-13
**Status:** Phase 1 Complete, Phase 2 TODOs Documented
