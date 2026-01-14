# MLB Player Name Matching Guide

**Created:** 2026-01-13
**Status:** Active - Critical for historical backfill

## Overview

Different MLB data sources use different player name formats. This document explains
the formats and how we handle matching between them.

## Data Source Formats

### 1. Predictions Table (`mlb_predictions.pitcher_strikeouts`)

**Source:** MLB Stats API via our analytics pipeline
**Format:** `first_last` (underscore separator)

Examples:
```
logan_webb
gerrit_cole
carlos_rodón      # Keeps accents
aj_smith-shawver  # Keeps hyphens
roddery_muñoz     # Keeps Spanish ñ
```

### 2. Historical Odds Table (`mlb_raw.oddsa_pitcher_props`)

**Source:** Odds API via `normalize_name_for_lookup()` function
**Format:** `firstlast` (no separators, no accents)

Examples:
```
loganwebb
gerritcole
carlosrodon       # Accents removed
ajsmithshawver    # Hyphens removed
rodderymunoz      # ñ → n
```

## The Matching Problem

Direct matching fails because:
```
logan_webb ≠ loganwebb
carlos_rodón ≠ carlosrodon
aj_smith-shawver ≠ ajsmithshawver
```

## The Solution

We normalize BOTH sides using SQL `TRANSLATE()` and `REPLACE()`:

```sql
LOWER(
    TRANSLATE(
        REPLACE(REPLACE(column_name, '_', ''), '-', ''),
        'áàâäãåéèêëíìîïóòôöõúùûüñç',
        'aaaaaaeeeeiiiiooooouuuunc'
    )
)
```

This:
1. Removes underscores (`_`)
2. Removes hyphens (`-`)
3. Converts accented characters to ASCII equivalents
4. Lowercases everything

### Result After Normalization

| Original | After Normalization |
|----------|-------------------|
| `logan_webb` | `loganwebb` |
| `carlos_rodón` | `carlosrodon` |
| `aj_smith-shawver` | `ajsmithshawver` |
| `roddery_muñoz` | `rodderymunoz` |

Both sides produce the same normalized output → matching works!

## Implementation Files

### Scripts Using This Logic

1. **`match_lines_to_predictions.py`** (Phase 3)
   - Uses `normalize_sql()` helper function
   - Applies to both prediction and odds lookups

2. **`validate_player_matching.py`**
   - Validates matching logic before backfill completes
   - Tests both Python normalizer and SQL TRANSLATE

### Normalizer Function

Located at: `shared/utils/player_name_normalizer.py`

```python
from shared.utils.player_name_normalizer import normalize_name_for_lookup

normalize_name_for_lookup("Carlos Rodón")  # Returns: "carlosrodon"
```

## Supported Special Characters

The TRANSLATE function handles these accented characters:

| Accented | ASCII |
|----------|-------|
| á à â ä ã å | a |
| é è ê ë | e |
| í ì î ï | i |
| ó ò ô ö õ | o |
| ú ù û ü | u |
| ñ | n |
| ç | c |

## Validation

Run validation before processing:

```bash
python scripts/mlb/historical_odds_backfill/validate_player_matching.py
```

Test specific pitcher:
```bash
python scripts/mlb/historical_odds_backfill/validate_player_matching.py --pitcher "Carlos Rodón"
```

## Known Edge Cases

### Handled ✓
- Underscores: `logan_webb` → `loganwebb`
- Hyphens: `smith-shawver` → `smithshawver`
- Spanish accents: `rodón` → `rodon`
- Spanish ñ: `muñoz` → `munoz`

### Not Currently Handled (Rare)
- Double-barreled names with apostrophes (none found in dataset)
- Non-Latin characters (none in MLB dataset)

## Troubleshooting

### Check if names will match

```sql
-- Test prediction side normalization
SELECT
    pitcher_lookup,
    LOWER(TRANSLATE(
        REPLACE(REPLACE(pitcher_lookup, '_', ''), '-', ''),
        'áàâäãåéèêëíìîïóòôöõúùûüñç',
        'aaaaaaeeeeiiiiooooouuuunc'
    )) as normalized
FROM mlb_predictions.pitcher_strikeouts
WHERE pitcher_name = 'Carlos Rodón';

-- Test odds side normalization
SELECT
    player_lookup,
    LOWER(TRANSLATE(
        REPLACE(REPLACE(player_lookup, '_', ''), '-', ''),
        'áàâäãåéèêëíìîïóòôöõúùûüñç',
        'aaaaaaeeeeiiiiooooouuuunc'
    )) as normalized
FROM mlb_raw.oddsa_pitcher_props
WHERE player_name LIKE '%Rod%'
  AND source_file_path LIKE '%pitcher-props-history%';
```

## Future Improvements

1. **MLB Player Registry**: Create authoritative player registry like NBA has
2. **Fuzzy Matching**: Add Levenshtein distance for edge cases
3. **Alias Table**: Store known name variations

## Related Documentation

- `ENHANCED-ANALYSIS-SCRIPTS.md` - Analysis script documentation
- `2026-01-14-SESSION-36-HANDOFF-BACKFILL-EXECUTION.md` - Backfill handoff
- `SESSION-HANDOFF-2026-01-13.md` - Original session handoff
