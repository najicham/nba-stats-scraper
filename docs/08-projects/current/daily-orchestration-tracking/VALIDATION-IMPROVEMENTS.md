# Validation Improvements

Track new validation queries, checks, or methods discovered during daily operations.
When mature, these should be added to the official validation docs.

---

## Improvement Template

```markdown
### [DATE] - Brief Description

**Discovered by:** Session N
**Status:** Proposed / Testing / Added to docs

**The Check:**
```sql
-- Query or command here
```

**Why It's Useful:**
- What problem it catches
- When to run it

**Add to:** Which doc should include this
```

---

## Proposed Improvements

### 2026-01-12 - BettingPros Props Count Check

**Discovered by:** Session 27
**Status:** Added to docs

**The Check:**
```sql
SELECT game_date, COUNT(*) as props
FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
WHERE game_date >= CURRENT_DATE() - 2
GROUP BY 1
HAVING COUNT(*) < 5000;
```

**Why It's Useful:**
- Catches missing BettingPros data before it affects predictions
- Run daily after betting_lines workflow

**Add to:**
- ✅ Added to `scripts/check_data_completeness.py`
- ✅ Added to `docs/00-start-here/DAILY-SESSION-START.md`

---

### 2026-01-12 - ESPN Roster Team Count Check

**Discovered by:** Session 26
**Status:** Added to docs

**The Check:**
```sql
SELECT roster_date, COUNT(DISTINCT team_abbr) as teams
FROM `nba-props-platform.nba_raw.espn_team_rosters`
WHERE roster_date >= CURRENT_DATE() - 3
GROUP BY 1 ORDER BY 1;
```

**Why It's Useful:**
- Catches incomplete ESPN roster scrapes (should be 30 teams)
- Early indicator of prediction pipeline issues

**Add to:**
- Should add to `scripts/check_data_completeness.py`

---

## Graduated to Docs

| Improvement | Added To | Date |
|-------------|----------|------|
| BettingPros props count | check_data_completeness.py | 2026-01-12 |
| BettingPros props count | DAILY-SESSION-START.md | 2026-01-12 |

---

*Add new improvements above the "Graduated" section*
