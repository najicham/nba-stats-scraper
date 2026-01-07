# Player Name Investigation: Why Registry Isn't Being Used

**Date:** December 29, 2025
**Status:** Investigation Complete

---

## Executive Summary

The player registry system exists and works correctly, but it's **not being used** in the critical path from odds ingestion to predictions. The result is player_lookup mismatches that cause ~15 players to be missing from predictions.

---

## The Two Root Causes

### Issue 1: Nickname vs Full Name Mismatches

The Odds API uses **nicknames** while the context/features use **full names**:

| Odds API (nickname) | Context (full name) | Registry Has |
|---------------------|---------------------|--------------|
| `herbjones` | `herbertjones` | Both (via alias) |
| `robertwilliams` | `robertwilliamsiii` | Both (via alias) |

The alias table has mappings, but they're in the **wrong direction**:
- Current: `robertwilliams` → `robertwilliamsiii` (without suffix → with suffix)
- Needed: `herbjones` → `herbertjones` (nickname → full name)

### Issue 2: Players Not in Context Despite Having Odds Lines

Some players have odds lines but aren't in the upcoming_player_game_context table:

| Player | Odds Has | Context Has | Reason |
|--------|----------|-------------|--------|
| `garytrentjr` | YES (MIL vs CHA) | NO | Not in context build |
| `jabarismithjr` | YES (HOU vs IND) | NO | Not in context build |
| `michaelporterjr` | YES (BKN vs GSW) | NO | Not in context build |

These players have **recent game history** (Dec 21-27) but weren't included in Dec 29 context.

---

## Code Flow Analysis

### Current Flow (Broken)

```
Odds API Response
    │
    ▼ normalize_name() - Simple lowercase/remove punctuation
OddsApiPropsProcessor (line 482)
    │
    ▼ player_lookup = "herbjones" (nickname preserved)
nba_raw.odds_api_player_points_props
    │
    ▼ NO registry lookup, NO alias resolution

Meanwhile...

Gamebook Data
    │
    ▼ normalize_name() - Same function
UpcomingPlayerGameContextProcessor
    │
    ▼ player_lookup = "herbertjones" (full name preserved)
nba_analytics.upcoming_player_game_context
    │
    ▼ Joins on player_lookup

MISMATCH: "herbjones" ≠ "herbertjones"
```

### Where Registry IS Used

The registry is used in two places, but **not for alias resolution in joins**:

1. **Prediction Worker** (`predictions/worker/worker.py:281`)
   ```python
   universal_player_id = player_registry.get_universal_id(player_lookup, required=False)
   ```
   - Only used to GET the universal_player_id
   - Doesn't resolve aliases before joins

2. **Context Processor** (`upcoming_player_game_context_processor.py:122`)
   ```python
   self.registry_reader = RegistryReader(source_name='upcoming_player_game_context')
   ```
   - Used for batch lookups
   - Logs unresolved players
   - Doesn't normalize player_lookup before storing

### Where Registry IS NOT Used (Problem Areas)

1. **Odds API Processor** (`odds_api_props_processor.py:482`)
   ```python
   'player_lookup': normalize_name(player_name)
   ```
   - Direct normalization, no registry lookup
   - No alias resolution

2. **ML Feature Store** (`ml_feature_store_processor.py`)
   - No RegistryReader import
   - Uses player_lookup as-is from source data

---

## The normalize_name() Function

**Location:** `data_processors/raw/utils/name_utils.py:14`

```python
def normalize_name(name: str) -> Optional[str]:
    # Convert to lowercase
    normalized = name.lower()

    # Remove accents and special characters
    normalized = ''.join(c for c in unicodedata.normalize('NFD', normalized)
                        if unicodedata.category(c) != 'Mn')

    # Remove apostrophes, periods, hyphens, and other punctuation
    normalized = re.sub(r"['\.\-\s]+", '', normalized)

    # Remove any remaining non-alphanumeric characters
    normalized = re.sub(r'[^a-z0-9]', '', normalized)

    return normalized
```

**Behavior:**
- "Herbert Jones" → `herbertjones`
- "Herb Jones" → `herbjones`
- "Gary Trent Jr." → `garytrentjr` (keeps "jr")
- "Robert Williams III" → `robertwilliamsiii` (keeps "iii")

The function preserves suffixes and nicknames, causing mismatches when different sources use different formats.

---

## Alias Table Analysis

**Table:** `nba_reference.player_aliases`

**Current Aliases (only 8 records):**

| alias_lookup | nba_canonical_lookup | Type |
|--------------|---------------------|------|
| `derrickwalton` | `derrickwaltonjr` | suffix_difference |
| `robertwilliams` | `robertwilliamsiii` | suffix_difference |
| `marcusmorris` | `marcusmorrissr` | suffix_difference |
| `kevinknox` | `kevinknoxii` | suffix_difference |
| `ggjacksonii` | `ggjackson` | suffix_difference |
| `xaviertillmansr` | `xaviertillman` | suffix_difference |
| `filippetruaev` | `filippetrusev` | encoding_difference |
| `matthewhurt` | `matthurt` | name_variation |

**Problem:** These aliases map Basketball-Reference format TO NBA format, but we need mappings FROM Odds API format TO our canonical format.

**Missing Aliases Needed:**

| alias_lookup (Odds API) | nba_canonical_lookup | Type |
|-------------------------|---------------------|------|
| `herbjones` | `herbertjones` | nickname |
| `garytrentjr` | `garytrent` | suffix_variation |
| (others to investigate) | | |

---

## Registry Data Quality Issue

The registry has **duplicate entries** for some players:

```sql
SELECT player_lookup, universal_player_id FROM nba_players_registry
WHERE player_lookup LIKE '%trent%';
```

| player_lookup | universal_player_id |
|---------------|---------------------|
| `garytrentjr` | `garytrentjr_001` |
| `garytrent` | `garytrent_001` |

These should be the SAME player with ONE universal_player_id, not two separate entries!

---

## Proposed Fix Architecture

### Option A: Normalize at Odds Ingestion (Recommended)

Add alias resolution to the odds processor:

```python
# odds_api_props_processor.py

from shared.utils.player_registry import RegistryReader

class OddsApiPropsProcessor:
    def __init__(self):
        ...
        self.registry_reader = RegistryReader(
            source_name='odds_api_props',
            cache_ttl_seconds=300
        )

    def transform_data(self):
        ...
        raw_lookup = normalize_name(player_name)

        # Try to resolve via registry/aliases
        canonical_lookup = self.registry_reader.resolve_lookup(raw_lookup)

        row = {
            'player_lookup': canonical_lookup or raw_lookup,
            'player_lookup_raw': raw_lookup,  # Keep original for debugging
            ...
        }
```

### Option B: Create Canonical Mapping Table

Create a dedicated mapping table for odds → canonical:

```sql
CREATE TABLE nba_reference.odds_player_mapping (
    odds_lookup STRING,
    canonical_lookup STRING,
    player_name STRING,
    source STRING,
    created_at TIMESTAMP
);
```

Then JOIN odds data through this mapping before predictions.

### Option C: Normalize Suffixes in normalize_name()

Modify normalize_name() to strip common suffixes:

```python
SUFFIX_PATTERNS = ['jr', 'sr', 'ii', 'iii', 'iv']

def normalize_name(name: str) -> Optional[str]:
    ...
    # Strip suffixes
    for suffix in SUFFIX_PATTERNS:
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)]

    return normalized
```

**Risk:** This changes behavior for ALL processors, could break other things.

---

## Recommended Approach

1. **Short-term:** Add missing aliases to `player_aliases` table
2. **Medium-term:** Integrate RegistryReader into odds processor (Option A)
3. **Long-term:** Clean up registry duplicates and establish canonical formats

---

## Missing Aliases to Add

```sql
INSERT INTO nba_reference.player_aliases
(alias_lookup, nba_canonical_lookup, alias_display, nba_canonical_display,
 alias_type, alias_source, is_active, notes, created_by, created_at, processed_at)
VALUES
('herbjones', 'herbertjones', 'Herb Jones', 'Herbert Jones',
 'nickname', 'odds_api', TRUE, 'Odds API uses nickname', 'investigation', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),

('garytrentjr', 'garytrent', 'Gary Trent Jr.', 'Gary Trent',
 'suffix_variation', 'odds_api', TRUE, 'Need to confirm canonical format', 'investigation', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP())
;
```

---

## Next Steps

1. [ ] Confirm canonical player_lookup format for each missing player
2. [ ] Add missing aliases to `player_aliases` table
3. [ ] Test that RegistryReader resolves these correctly
4. [ ] Integrate RegistryReader into odds processor
5. [ ] Add monitoring for unresolved player lookups in odds data
