# Recurring Patterns & Solutions

Document patterns that appear multiple times and their reliable fixes.

---

## Pattern Template

```markdown
### Pattern Name

**Frequency:** How often seen
**Last Seen:** Date

**Symptoms:**
- What you observe

**Root Cause:**
- Why it happens

**Reliable Fix:**
- Steps to resolve

**Prevention:**
- How to avoid in future
```

---

## Known Patterns

### BettingPros API Timeouts

**Frequency:** Occasional (1-2x per week)
**Last Seen:** 2026-01-12

**Symptoms:**
- `betting_pros_player_props` scraper fails
- Error: "No events found for date" or timeout errors
- BettingPros props missing from BigQuery

**Root Cause:**
- Proxy instability (502, connection timeouts)
- BettingPros API slow during peak times
- Paginated requests compound timeout risk

**Reliable Fix:**
```bash
# Trigger all market types manually
for market in points rebounds assists threes steals blocks; do
  curl -X POST "https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/scrape" \
    -H "Content-Type: application/json" \
    -d "{\"scraper\": \"bp_player_props\", \"date\": \"YYYY-MM-DD\", \"market_type\": \"$market\", \"group\": \"prod\"}"
  sleep 5
done
```

**Prevention:**
- Session 27 implemented timeout increase and retry logic
- Recovery script: `scripts/betting_props_recovery.py`

---

### ESPN Roster Incomplete Scrape

**Frequency:** Occasional (every few days)
**Last Seen:** 2026-01-09

**Symptoms:**
- ESPN rosters table has < 30 teams for today
- Predictions may be affected

**Root Cause:**
- ESPN rate limiting (429 responses)
- Previous threshold too low (25/30)

**Reliable Fix:**
```bash
# Re-run ESPN roster scraper
curl -X POST "https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/scrape" \
  -H "Content-Type: application/json" \
  -d '{"scraper": "espn_team_roster_api", "group": "prod"}'
```

**Prevention:**
- Session 26 raised threshold to 29/30 and added adaptive rate limiting

---

### West Coast Games Missing from BDL

**Frequency:** Was daily before fix
**Last Seen:** 2026-01-11 (should be fixed now)

**Symptoms:**
- BDL box scores missing for late-night games (LAL, LAC, SAC, etc.)
- Games finishing after 1 AM ET not captured

**Root Cause:**
- post_game_window_3 ran before west coast games finished

**Reliable Fix:**
- Wait for next overnight processing, or
- Manually trigger BDL scraper for the date

**Prevention:**
- Session 25 added multiple collection windows and later timing

---

*Add new patterns above this line*
