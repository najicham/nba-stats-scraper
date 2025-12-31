# Incident Postmortem: Gamebook Collection Gap

**Date:** 2025-12-28
**Severity:** Medium (data quality, not outage)
**Duration:** ~24 hours (Dec 27 games affected)
**Resolution:** Code fix + manual backfill

---

## Executive Summary

On Dec 28, during morning monitoring, we discovered that only 1 of 9 gamebooks were collected for Dec 27 games. The root cause was a "Phase 1" code limitation in the parameter resolver that was documented but never upgraded. The issue was fixed, deployed, and data was backfilled within 2 hours.

---

## Timeline

| Time (ET) | Event |
|-----------|-------|
| Dec 27, 10 PM | post_game_window_1 runs - only processes 1 game |
| Dec 28, 1 AM | post_game_window_2 runs - only processes 1 game |
| Dec 28, 4 AM | post_game_window_3 runs - only processes 1 game |
| Dec 28, 4:38 AM | BrokenPipeError emails sent (transient GCS errors) |
| Dec 28, 10:54 AM | Morning check discovers issue (1/9 gamebooks) |
| Dec 28, 11:15 AM | Root cause identified in parameter_resolver.py |
| Dec 28, 11:25 AM | Fix deployed to nba-phase1-scrapers |
| Dec 28, 11:44 AM | Backfill complete (9/9 gamebooks) |
| Dec 28, 11:49 AM | Data verified in BigQuery |

---

## Root Cause Analysis

### Primary Cause: "Phase 1" Code Never Upgraded

The `_resolve_nbac_gamebook_pdf()` function was written with an intentional limitation:

```python
def _resolve_nbac_gamebook_pdf(self, context):
    games = context.get('games_today', [])
    if not games:
        return {}

    # Phase 1: Just return first game
    # Phase 2: Return list of params for all games  <-- NEVER DONE
    game = games[0]  # <-- BUG: Only first game!

    return {'game_code': f"{date}/{away}{home}"}
```

The workflow executor already supported list returns (added in earlier development), but the resolver was never upgraded. This is **technical debt that was documented but forgotten**.

### Contributing Factors

1. **No completeness validation**
   - System logs "success" for each run
   - No check: "Did we get ALL expected games?"

2. **Misleading success metrics**
   - Log showed: `nbac_gamebook_pdf: 2025-12-27 - success (3 records)`
   - Looked correct, but was only 1/9 games

3. **Self-heal blind spot**
   - Self-heal checks for missing predictions
   - Doesn't check upstream data completeness

4. **Similar code in other resolvers**
   - `_resolve_nbac_play_by_play()` - same issue
   - `_resolve_game_specific()` - same issue
   - These may be intentional (date-based scrapers) or bugs

### Secondary Issue: BrokenPipeError

Transient network errors during GCS uploads:
- Caused by proxy connection drops
- Some uploads failed silently
- Separate from the resolver bug but compounds the problem

---

## Impact

### Data Affected
- **Dec 27 gamebooks:** 8/9 games missing until backfill
- **DNP reasons:** Not available for 8 games
- **Attendance data:** Not available for 8 games

### Systems Affected
- Gamebook data in BigQuery
- Any analytics depending on DNP intelligence

### User Impact
- None directly (gamebooks are supplementary data)
- Predictions still ran with available box score data

---

## Resolution

### Immediate Fix
Changed resolver to return list of all games:

```python
def _resolve_nbac_gamebook_pdf(self, context) -> List[Dict]:
    games = context.get('games_today', [])
    if not games:
        return []

    params_list = []
    for game in games:  # ALL games now!
        game_code = f"{date}/{away}{home}"
        params_list.append({'game_code': game_code})

    return params_list
```

### Backfill
```bash
PYTHONPATH=. python scripts/backfill_gamebooks.py --date 2025-12-27
# Result: 9/9 games, 315 player rows
```

---

## Prevention Measures

### Immediate (This Week)

#### 1. Add Completeness Check to Cleanup Processor
```python
def check_gamebook_completeness(self, target_date):
    """Compare scheduled games vs collected gamebooks."""
    query = """
    SELECT
        s.game_date,
        COUNT(DISTINCT s.game_id) as expected,
        COUNT(DISTINCT g.game_id) as actual
    FROM nba_raw.nbac_schedule s
    LEFT JOIN nba_raw.nbac_gamebook_player_stats g
        ON s.game_id = g.game_id AND s.game_date = g.game_date
    WHERE s.game_date = @date AND s.game_status = 3
    GROUP BY s.game_date
    """
    result = execute_query(query, {'date': target_date})

    if result.actual < result.expected:
        self.alert(
            f"GAMEBOOK INCOMPLETE: {result.actual}/{result.expected} "
            f"games for {target_date}"
        )
        return False
    return True
```

#### 2. Add to Daily Health Summary Email
```
=== Data Completeness (Yesterday) ===
Scheduled games: 9
Gamebooks: 9/9 (100%) ✅
Box scores: 9/9 (100%) ✅
Play-by-play: 9/9 (100%) ✅
```

#### 3. Audit Similar Resolvers
Review these for same issue:
- [ ] `_resolve_nbac_play_by_play()`
- [ ] `_resolve_game_specific()`
- [ ] `_resolve_game_specific_with_game_date()`

### Short-Term (Next Sprint)

#### 4. Extend Self-Heal Function
```python
def check_upstream_data_completeness(game_date):
    """Check gamebooks, box scores before running predictions."""
    checks = [
        check_gamebook_completeness(game_date),
        check_boxscore_completeness(game_date),
    ]

    if not all(checks):
        trigger_backfill_for_missing()
        return False
    return True
```

#### 5. Enhanced Workflow Logging
Change from:
```
nbac_gamebook_pdf: 2025-12-27 - success (3 records)
```
To:
```
nbac_gamebook_pdf: 2025-12-27 - success (3 records) [Game 1/9: DAL@SAC]
```

#### 6. Morning Monitoring Script
```bash
#!/bin/bash
# bin/monitoring/overnight_completeness.sh
# Run at 5 AM ET after post_game_window_3

echo "=== Overnight Collection Completeness ==="
YESTERDAY=$(date -d "yesterday" +%Y-%m-%d)

# Check gamebooks
EXPECTED=$(bq query "SELECT COUNT(*) FROM schedule WHERE date='$YESTERDAY' AND status=3")
ACTUAL=$(bq query "SELECT COUNT(DISTINCT game_id) FROM gamebooks WHERE date='$YESTERDAY'")

if [ "$ACTUAL" -lt "$EXPECTED" ]; then
    echo "❌ GAMEBOOKS INCOMPLETE: $ACTUAL/$EXPECTED"
    # Trigger backfill or alert
else
    echo "✅ Gamebooks: $ACTUAL/$EXPECTED"
fi
```

### Long-Term (Backlog)

#### 7. Data Quality Dashboard
Create BigQuery view for monitoring:
```sql
CREATE VIEW nba_monitoring.data_completeness AS
SELECT
    s.game_date,
    COUNT(DISTINCT s.game_id) as scheduled_games,
    COUNT(DISTINCT g.game_id) as gamebook_games,
    COUNT(DISTINCT b.game_id) as boxscore_games,
    ROUND(100.0 * COUNT(DISTINCT g.game_id) /
          NULLIF(COUNT(DISTINCT s.game_id), 0), 1) as gamebook_pct,
    ROUND(100.0 * COUNT(DISTINCT b.game_id) /
          NULLIF(COUNT(DISTINCT s.game_id), 0), 1) as boxscore_pct
FROM nba_raw.nbac_schedule s
LEFT JOIN nba_raw.nbac_gamebook_player_stats g
    ON s.game_id = g.game_id
LEFT JOIN nba_raw.bdl_player_boxscores b
    ON s.game_id = b.game_id
WHERE s.game_status = 3
GROUP BY s.game_date
```

#### 8. Automated Backfill Triggers
When completeness < 100%, automatically trigger backfill jobs.

---

## Lessons Learned

### What Went Well
1. Morning monitoring caught the issue
2. Root cause was identified quickly (20 min)
3. Fix + deploy + backfill completed in 2 hours
4. Existing backfill script worked perfectly
5. No downstream impact on predictions

### What Went Wrong
1. "Phase 1" limitation was documented but never addressed
2. No completeness validation caught the gap
3. Success logs were misleading (looked fine, wasn't)
4. Similar patterns exist in other resolvers

### Action Items

| Priority | Item | Owner | Status |
|----------|------|-------|--------|
| P0 | Fix gamebook resolver | Done | ✅ |
| P1 | Add completeness check to cleanup_processor | TBD | |
| P1 | Audit similar resolvers | TBD | |
| P2 | Add to daily health email | TBD | |
| P2 | Create monitoring script | TBD | |
| P3 | Extend self-heal | TBD | |
| P3 | Data quality dashboard | TBD | |

---

## Related Documents

- Session 180 Handoff: `docs/09-handoff/2025-12-28-SESSION180-GAMEBOOK-FIX.md`
- Parameter Resolver: `orchestration/parameter_resolver.py`
- Backfill Script: `scripts/backfill_gamebooks.py`
- Self-Heal Function: `orchestration/cloud_functions/self_heal/main.py`
