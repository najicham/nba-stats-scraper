# Session 7: Coverage Check Alias Resolution

**Date:** 2026-01-10
**Status:** Complete
**Coverage Impact:** 90.4% -> 93.2%

---

## Problem Identified

The coverage check was reporting 90.4% coverage (14 gaps) for Jan 9, but investigation revealed that aliases weren't being used correctly in the coverage calculations.

### Root Cause

1. **Betting APIs use legal names** (e.g., `carltoncarrington`, `nicolasclaxton`)
2. **Our data stores use roster names** (e.g., `bubcarrington`, `nicclaxton`)
3. **Aliases existed** but coverage check wasn't using them for predictions matching

Players like `carltoncarrington` had predictions stored under their canonical name `bubcarrington`, but the coverage check wasn't resolving aliases.

---

## Fix Applied

Updated `tools/monitoring/check_prediction_coverage.py` to add comprehensive alias resolution:

### 1. Coverage Summary Query

Added alias-resolved prediction matching:
```sql
LEFT JOIN aliases a ON bl.player_lookup = a.alias_lookup
LEFT JOIN predictions p_via_alias ON a.nba_canonical_lookup = p_via_alias.player_lookup
```

### 2. Coverage Gaps Query

Added alias resolution for ALL lookups:
- **Registry membership**: Check canonical name via alias
- **Player context**: Use COALESCE for alias-resolved context
- **Features**: Use COALESCE for alias-resolved features
- **Predictions**: Check both direct and alias-resolved matches

### 3. DID_NOT_PLAY Detection

Added new gap category to identify players who had betting lines but didn't play:
```sql
-- Players who actually played (have box score data)
played_game AS (
    SELECT DISTINCT player_lookup
    FROM nba_analytics.player_game_summary
    WHERE game_date = @game_date
)
```

Gap reason now includes:
- `DID_NOT_PLAY`: Player had betting lines but no box score (injury scratch)

---

## Results

### Before (Session 6)
```
Total players with betting lines: 146
Players with predictions:         132
Coverage gap:                     14
Coverage percentage:              90.4%
```

### After (Session 7)
```
Total players with betting lines: 146
Players with predictions:         136
Coverage gap:                     10
Coverage percentage:              93.2%
```

### Gap Breakdown

| Reason | Count | Notes |
|--------|-------|-------|
| DID_NOT_PLAY | 8 | jamalmurray, kristapsporzingis, zaccharierisacher, tristandasilva (x2 each) - players scratched late |
| NO_FEATURES | 5 | brandoningram, marvinbagleyiii, ruihachimura, ziairewilliams, ochaiagbaji - new/traded players |
| NOT_IN_PLAYER_CONTEXT | 1 | jimmybutler - injured/out |

---

## Alias Resolution Now Covers

1. **Coverage summary**: Correctly counts predictions via aliases
2. **Gap details**: Shows team/context from alias-resolved data
3. **Gap categorization**: Uses alias-resolved registry, context, and features

---

## Files Changed

| File | Change |
|------|--------|
| `tools/monitoring/check_prediction_coverage.py` | Added comprehensive alias resolution, DID_NOT_PLAY detection |

---

## Verification

```bash
python tools/monitoring/check_prediction_coverage.py --date 2026-01-09 --detailed
```

Coverage improved from 90.4% to 93.2%. Remaining gaps are expected (players who didn't play or lack data).

---

**Commit:** fb7a894
**Author:** Claude Code (Opus 4.5)
