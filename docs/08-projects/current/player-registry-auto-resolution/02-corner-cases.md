# Corner Cases and Edge Conditions

**Last Updated:** 2026-01-22

This document catalogs all edge cases we've identified in the player resolution system and how our solution handles each one.

## Table of Contents

1. [Name Variation Cases](#1-name-variation-cases)
2. [Temporal Cases](#2-temporal-cases)
3. [Data Quality Cases](#3-data-quality-cases)
4. [System Integration Cases](#4-system-integration-cases)
5. [Reprocessing Cases](#5-reprocessing-cases)

---

## 1. Name Variation Cases

### 1.1 Same Player, Different Spellings

**Scenario:** Multiple sources report the same player with different name formats.

| Source | Name Format | Normalized |
|--------|-------------|------------|
| NBA.com | "LeBron James" | "lebronjames" |
| ESPN | "L. James" | "ljames" |
| BettingPros | "Lebron James" | "lebronjames" |
| BDL | "James, LeBron" | "jameslebron" |

**Problem:** "ljames" and "jameslebron" won't match "lebronjames" in registry.

**Solution:**
```
Stage 1 (Fuzzy Match):
  • "ljames" → fuzzy match "lebronjames" = 72% → NOT auto-resolved
  • "jameslebron" → fuzzy match "lebronjames" = 85% → NOT auto-resolved

Stage 2 (AI Resolution):
  • Context provided: team=LAL, season=2025-26, roster=[lebronjames, anthonydavis, ...]
  • AI determines: "ljames" on LAL = LeBron James (only L. James on roster)
  • AI determines: "jameslebron" = reversed name format of LeBron James
  • Both mapped to universal_player_id "lebronjames_001"
```

**Validation Rule:** AI must verify player was on the team in that season.

---

### 1.2 Players with Same Name (Disambiguation)

**Scenario:** Multiple players with identical names exist in the league.

| Player | Team | Seasons |
|--------|------|---------|
| Marcus Morris Sr. | CLE | 2023-present |
| Marcus Morris Jr. | LAC | 2019-2023, then POR |
| Marcus Morris (G-League) | SLC | 2025 |

**Problem:** "marcusmorris" could map to any of these players.

**Solution:**
```
Stage 1 (Fuzzy Match):
  • "marcusmorris" matches multiple → SKIP auto-resolution (ambiguous)

Stage 2 (AI Resolution):
  • Context: team_abbr, game_date, season
  • AI cross-references:
    - Which Marcus Morris was on that team in that season?
    - Check roster data for team + date
  • If unambiguous: Create alias with team context
  • If ambiguous: Mark as 'needs_review'
```

**Schema Addition:** `player_aliases` now includes `valid_team_abbr` and `valid_season` columns:
```sql
CREATE TABLE player_aliases (
  alias_lookup STRING,
  canonical_lookup STRING,
  valid_team_abbr STRING,      -- Only apply alias when player on this team
  valid_season STRING,         -- Only apply alias for this season (e.g., "2025-26")
  is_active BOOL,
  created_at TIMESTAMP
);
```

**Lookup Logic:**
```python
# When resolving "marcusmorris" for LAC in 2022-23:
SELECT canonical_lookup
FROM player_aliases
WHERE alias_lookup = 'marcusmorris'
  AND (valid_team_abbr IS NULL OR valid_team_abbr = 'LAC')
  AND (valid_season IS NULL OR valid_season = '2022-23')
  AND is_active = TRUE
ORDER BY valid_team_abbr DESC, valid_season DESC  -- Prefer specific matches
LIMIT 1
```

---

### 1.3 Special Characters and Encoding

**Scenario:** Names with accents, hyphens, apostrophes.

| Original | Source Encoding | Our Encoding |
|----------|-----------------|--------------|
| "Nikola Jokić" | "Nikola Jokic" | "nikolajokic" |
| "Shai Gilgeous-Alexander" | "Shai Gilgeous Alexander" | "shagilgeousalexander" |
| "Dennis Schröder" | "Dennis Schroder" | "dennisschroder" |
| "O.G. Anunoby" | "OG Anunoby" | "oganunoby" |

**Problem:** Inconsistent handling of special characters across sources.

**Solution:**
```python
# Standardized normalization (shared/utils/player_name_normalizer.py)
def normalize_name(name: str) -> str:
    # 1. Convert accented characters to ASCII
    name = unidecode(name)  # "Jokić" → "Jokic"

    # 2. Remove all punctuation and special characters
    name = re.sub(r'[^a-zA-Z]', '', name)

    # 3. Lowercase
    name = name.lower()

    # 4. Handle known edge cases
    name = KNOWN_NORMALIZATIONS.get(name, name)

    return name

KNOWN_NORMALIZATIONS = {
    'oganunoby': 'oganunoby',      # O.G. → OG
    'pjwashington': 'pjwashington', # P.J. → PJ
    'cjmccollum': 'cjmccollum',     # C.J. → CJ
}
```

---

### 1.4 Name Changes (Legal Name Changes, Preferred Names)

**Scenario:** Player legally changes name or uses different preferred name.

| Original | New Name | When Changed |
|----------|----------|--------------|
| "Enes Kanter" | "Enes Freedom" | 2021 |
| "Elfrid Payton Jr." | "Elfrid Payton" | Varies by source |

**Problem:** Historical data uses old name, new data uses new name.

**Solution:**
```sql
-- player_name_history table tracks name changes
CREATE TABLE player_name_history (
  universal_player_id STRING,
  lookup_name STRING,
  valid_from DATE,
  valid_to DATE,  -- NULL for current name
  change_type STRING,  -- 'legal_change', 'preferred_name', 'nickname'
  created_at TIMESTAMP
);

-- Historical data:
INSERT INTO player_name_history VALUES
  ('eneskanter_001', 'eneskanter', '2015-01-01', '2021-11-01', 'legal_change'),
  ('eneskanter_001', 'enesfreedom', '2021-11-01', NULL, 'legal_change');
```

**Resolution Logic:**
```python
def resolve_with_history(lookup: str, game_date: date) -> str:
    # Check current aliases first
    alias_result = resolve_via_alias(lookup)
    if alias_result:
        return alias_result

    # Check historical names
    query = """
        SELECT universal_player_id
        FROM player_name_history
        WHERE lookup_name = @lookup
          AND @game_date BETWEEN valid_from AND COALESCE(valid_to, '2099-12-31')
    """
    # Returns correct player based on when game was played
```

---

## 2. Temporal Cases

### 2.1 Rookie Not Yet in Registry

**Scenario:** New draft pick plays before registry is updated.

**Timeline:**
```
June 2026: Player drafted
October 2026: Season starts, player appears in boxscores
Registry: Still only has previous season's players
```

**Problem:** Legitimate player marked as "unresolved" because registry is outdated.

**Solution:**
```
Stage 2 (AI Resolution):
  • AI context includes: draft class, team transactions, news
  • AI determines: This is a new player, not a typo
  • Action: Create NEW registry entry (not alias)

Schema:
  • registry entry created with source='ai_resolution'
  • Flag: requires_verification=TRUE
  • Notification sent for human verification
```

**Verification Workflow:**
```python
# Daily job checks unverified AI-created entries
def verify_ai_created_players():
    query = """
        SELECT * FROM nba_players_registry
        WHERE source = 'ai_resolution'
          AND requires_verification = TRUE
          AND created_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
    """
    # After 7 days, if player has consistent data across sources:
    # - Mark requires_verification = FALSE
    # - Otherwise, escalate for manual review
```

---

### 2.2 Player Traded Mid-Season

**Scenario:** Player trades between teams, name appears for different teams.

| Date | Team | Player |
|------|------|--------|
| Jan 1 | PHO | "K. Durant" |
| Jan 15 | Trade to BOS | |
| Jan 20 | BOS | "Kevin Durant" |

**Problem:** Same player, different name formats, different teams.

**Solution:**
```
AI Resolution Context:
  • Check trade history: Was Kevin Durant traded to BOS around Jan 15?
  • If yes: Both resolve to same universal_player_id
  • Alias created: "kdurant" → "kevindurant" (no team restriction needed)
```

---

### 2.3 Historical Backfill Finds Old Names

**Scenario:** Running backfill for 2021 data, names from 3+ years ago.

**Problem:**
- Registry may not have players who retired
- Name formats may have changed
- AI context (current rosters) doesn't help

**Solution:**
```python
def ai_resolve_historical(lookup: str, game_date: date, team_abbr: str):
    # Use historical roster for that season
    season = get_season_for_date(game_date)  # "2021-22"

    historical_roster = query("""
        SELECT player_name, player_lookup
        FROM nba_rosters_historical
        WHERE team_abbr = @team_abbr
          AND season = @season
    """)

    # Provide historical context to AI
    ai_context = {
        'unresolved_lookup': lookup,
        'game_date': game_date,
        'team_abbr': team_abbr,
        'team_roster': historical_roster,  # Historical, not current
        'registry_similar': get_similar_from_registry(lookup)
    }

    return ai_resolver.resolve_single(ai_context)
```

---

## 3. Data Quality Cases

### 3.1 Typos in Source Data

**Scenario:** Source data contains obvious typos.

| Source | Value | Likely Intended |
|--------|-------|-----------------|
| ESPN | "Lebron Jmes" | "LeBron James" |
| BettingPros | "Steph Currry" | "Stephen Curry" |

**Problem:** Typos should not create aliases (would persist the error).

**Solution:**
```
Stage 2 (AI Resolution):
  • AI detects: "lebronjmes" is likely typo of "lebronjames"
  • Decision: DATA_ERROR (not MATCH)
  • Action:
    - Mark as 'invalid' in unresolved_player_names
    - Cache as DATA_ERROR (won't reprocess)
    - Do NOT create alias

Rationale:
  • Creating alias would mean future typos auto-resolve
  • Better to fix at source or skip these records
```

---

### 3.2 Partial Names

**Scenario:** Source only provides partial name.

| Source | Value | Problem |
|--------|-------|---------|
| Odds API | "A. Davis" | Multiple "A. Davis" exist |
| BettingPros | "James" | LeBron? James Harden? James Wiseman? |

**Solution:**
```
Stage 2 (AI Resolution):
  • If partial name is unambiguous for team:
    - "A. Davis" on LAL = Anthony Davis (only one)
    - Create alias with team restriction
  • If ambiguous:
    - Mark as 'needs_review'
    - Cannot auto-resolve

Validation:
  • Count players matching "A. Davis" on that team
  • If count > 1: Cannot auto-resolve
```

---

### 3.3 G-League / Two-Way Players

**Scenario:** Players moving between NBA and G-League.

**Problem:**
- May not be in registry when first encountered
- May have different IDs in G-League vs NBA
- May appear sporadically

**Solution:**
```python
# When AI determines: NEW_PLAYER (G-League/Two-Way)
def create_developmental_player(lookup: str, context: dict):
    # Create registry entry with flags
    entry = {
        'universal_player_id': generate_id(lookup),
        'player_lookup': lookup,
        'player_type': 'developmental',  # G-League, two-way, etc.
        'requires_verification': True,
        'source': 'ai_resolution',
        'first_seen_team': context['team_abbr'],
        'first_seen_date': context['game_date']
    }

    # Lower confidence threshold for reprocessing
    # (don't reprocess all historical games for G-League callup)
```

---

## 4. System Integration Cases

### 4.1 Race Condition: Multiple Jobs Resolving Same Player

**Scenario:** Parallel processes try to resolve the same unresolved name.

**Problem:** Could create duplicate aliases or inconsistent state.

**Solution:**
```sql
-- Use BigQuery MERGE with unique constraint
MERGE INTO player_aliases AS target
USING (SELECT @alias_lookup AS alias_lookup, @canonical AS canonical) AS source
ON target.alias_lookup = source.alias_lookup
WHEN NOT MATCHED THEN
  INSERT (alias_lookup, canonical_lookup, created_at)
  VALUES (source.alias_lookup, source.canonical, CURRENT_TIMESTAMP())
-- WHEN MATCHED: Do nothing (already exists)
```

```python
# Resolution job uses optimistic locking
def resolve_player(lookup: str):
    # Check if already being processed
    lock_key = f"resolution:{lookup}"
    if not acquire_lock(lock_key, ttl=300):
        logger.info(f"Skipping {lookup}, already being processed")
        return

    try:
        do_resolution(lookup)
    finally:
        release_lock(lock_key)
```

---

### 4.2 Cascade Failure: Resolution Succeeds, Reprocessing Fails

**Scenario:** Alias created successfully, but game reprocessing fails.

**Problem:** Player marked as "resolved" but data still incomplete.

**Solution:**
```python
def resolve_and_reprocess(lookup: str) -> ResolutionResult:
    # Step 1: Create alias (transaction 1)
    alias_created = create_alias(lookup, canonical)

    if not alias_created:
        return ResolutionResult(status='failed', stage='alias_creation')

    # Step 2: Reprocess games (may fail partially)
    reprocess_results = []
    for game_id in affected_games:
        try:
            result = reprocess_game(game_id)
            reprocess_results.append(result)
        except Exception as e:
            # Log failure but continue
            log_reprocess_failure(game_id, e)
            reprocess_results.append({'game_id': game_id, 'status': 'failed'})

    # Step 3: Update status based on results
    success_rate = sum(1 for r in reprocess_results if r['status'] == 'success') / len(reprocess_results)

    if success_rate == 1.0:
        mark_fully_resolved(lookup)
    elif success_rate > 0:
        mark_partially_resolved(lookup, reprocess_results)
    else:
        mark_reprocess_failed(lookup)
        # Don't rollback alias - it's still valid

    return ResolutionResult(
        status='partial' if 0 < success_rate < 1 else 'success' if success_rate == 1 else 'failed',
        alias_created=True,
        games_processed=reprocess_results
    )
```

---

### 4.3 AI Rate Limits and Costs

**Scenario:** Large batch of unresolved names exhausts AI API limits.

**Problem:**
- Claude API has rate limits
- Cost per resolution adds up
- Must not block pipeline

**Solution:**
```python
# ai_resolver.py already has rate limiting built-in
AI_RESOLUTION_CONFIG = {
    'max_batch_size': 100,           # Process max 100 per run
    'rate_limit_per_minute': 50,     # Claude rate limit
    'cost_per_resolution': 0.000003, # ~$0.003 per 1000
    'daily_budget_usd': 1.00,        # Max $1/day on AI resolution
    'priority_order': [              # Process in this order
        'has_prop_lines',            # Players with betting lines first
        'recent_games',              # Recent games before historical
        'high_occurrence',           # Frequently appearing names
    ]
}

def ai_resolve_batch_with_budget(unresolved: List[str]):
    budget_remaining = get_daily_budget_remaining()
    max_resolutions = int(budget_remaining / AI_RESOLUTION_CONFIG['cost_per_resolution'])

    # Prioritize which names to resolve
    prioritized = prioritize_unresolved(unresolved)

    # Only process up to budget
    to_process = prioritized[:min(len(prioritized), max_resolutions)]

    return ai_resolver.resolve_batch(to_process)
```

---

## 5. Reprocessing Cases

### 5.1 How Far Back Should We Reprocess?

**Scenario:** Player resolved today, but appears in games going back months.

**Decision Matrix:**

| Games Age | Action | Rationale |
|-----------|--------|-----------|
| < 7 days | Always reprocess | Recent = important for predictions |
| 7-30 days | Reprocess if prop lines existed | Affects historical accuracy metrics |
| 30-90 days | Reprocess on request | Batch backfill job |
| > 90 days | Skip unless explicit backfill | Diminishing returns |

**Implementation:**
```python
def get_games_to_reprocess(player_lookup: str, resolved_at: datetime) -> List[str]:
    cutoff_7_days = resolved_at - timedelta(days=7)
    cutoff_30_days = resolved_at - timedelta(days=30)

    # Tier 1: All games in last 7 days
    tier1_games = query("""
        SELECT game_id FROM registry_failures
        WHERE player_lookup = @lookup
          AND game_date >= @cutoff_7_days
    """)

    # Tier 2: Games 7-30 days ago WITH prop lines
    tier2_games = query("""
        SELECT rf.game_id
        FROM registry_failures rf
        JOIN prop_lines pl ON rf.game_id = pl.game_id AND rf.player_lookup = pl.player_lookup
        WHERE rf.player_lookup = @lookup
          AND rf.game_date >= @cutoff_30_days
          AND rf.game_date < @cutoff_7_days
    """)

    return tier1_games + tier2_games
```

---

### 5.2 Reprocessing Order: Ascending vs Descending Dates

**Scenario:** Player has 50 games to reprocess spanning 3 months.

**Decision:** Process **DESCENDING** (newest first)

**Rationale:**
```
Newest games are most important because:
1. Predictions are generated for upcoming games (need recent stats)
2. Recent performance affects model features
3. If budget/time runs out, oldest games matter least

Exception: Full historical backfill
- When doing full season backfill, process chronologically
- Stats depend on prior games (streak calculations, etc.)
```

---

### 5.3 Reprocessing Triggers Downstream Cascade

**Scenario:** Reprocessing game updates `player_game_summary`, which should update Phase 4 and Phase 5.

**Solution:**
```python
def reprocess_game_with_cascade(game_id: str):
    # Step 1: Reprocess Phase 3
    result = PlayerGameSummaryProcessor.process_single_game(game_id)

    if result['success']:
        # Step 2: Trigger Phase 4 for affected players
        affected_players = result['players_updated']
        for player_id in affected_players:
            publish_to_topic('phase4-precompute-trigger', {
                'player_id': player_id,
                'game_id': game_id,
                'trigger': 'registry_resolution'
            })

        # Step 3: Phase 5 will automatically run after Phase 4
        # (existing cascade handles this)

    return result
```

---

## Summary: Resolution Decision Tree

```
Unresolved Name Received
         │
         ▼
┌─────────────────────┐
│  Fuzzy Match ≥95%   │
│  Same Team/Season   │
└─────────────────────┘
         │
    ┌────┴────┐
    │ YES     │ NO
    ▼         ▼
AUTO-RESOLVE  ┌─────────────────────┐
              │   AI Resolution     │
              │   (Claude Haiku)    │
              └─────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
      MATCH        NEW_PLAYER    DATA_ERROR
    (≥80% conf)    (≥80% conf)   (≥80% conf)
         │             │             │
         ▼             ▼             ▼
   Create Alias   Create Entry   Mark Invalid
         │             │             │
         └──────┬──────┘             │
                ▼                    ▼
         Reprocess Games        Skip/Log
                │
                ▼
         Cascade to P4/P5
                │
                ▼
              DONE

AI Confidence <80%:
         │
         ▼
   Mark 'needs_review'
         │
         ▼
   Daily Slack Alert
         │
         ▼
   Manual Review
```
