# Proxy Infrastructure Incident Log

## 2026-01-22: ProxyFuel IP Block Incident

### Summary
Multiple target sites started blocking ProxyFuel proxy IPs, causing widespread scraper failures.

### Timeline
- **~00:05 UTC:** `betting_lines` workflow ran, `oddsa_events` failing
- **~01:00 UTC:** Last successful props data loaded for Jan 21
- **~11:00 UTC:** Issue identified during daily validation
- **~18:30 UTC:** Root cause confirmed - 403 Forbidden from BettingPros

### Affected Systems
| System | Impact |
|--------|--------|
| `bp_events` | 403 Forbidden |
| `bp_player_props` | Cannot run (depends on events) |
| `oddsa_events` | 403/Timeout |
| `oddsa_player_props` | Cannot run |
| `nbac_team_boxscore` | Timeout |

### Root Cause
Target websites (BettingPros, OddsAPI, NBA.com stats API) are actively blocking ProxyFuel's datacenter IP ranges.

**Evidence:**
```bash
# Proxy itself works (httpbin returns 200)
curl -x "http://...@gate2.proxyfuel.com:2000" "http://httpbin.org/ip"
# Returns: {"origin": "45.145.128.103"}

# BettingPros blocks
curl -x "http://...@gate2.proxyfuel.com:2000" "https://api.bettingpros.com/v3/events..."
# Returns: {"message":"Forbidden"} (HTTP 403)
```

### Impact
- No betting props data for Jan 22
- `upcoming_team_game_context` = 0 (Phase 3 staleness check fails)
- Predictions for Jan 22 may be incomplete

### Actions Taken
1. ✅ Diagnosed proxy as root cause (not credits issue)
2. ✅ Created `proxy_health_metrics` table for future monitoring
3. ✅ Added proxy health logging to scraper base
4. ✅ Documented proxy provider alternatives
5. ⏳ Evaluating Decodo/Smartproxy as replacement

### Lessons Learned
1. **Need proactive monitoring:** Should alert when proxy success rate drops
2. **Datacenter IPs are risky:** Residential proxies harder to block
3. **Have backup provider ready:** Faster recovery if pre-configured

### Prevention Measures
1. Add proxy health to daily health check
2. Alert when success rate < 80% for any target
3. Maintain relationship with backup proxy provider
4. Consider direct access (no proxy) where possible

---

## Template for Future Incidents

```markdown
## YYYY-MM-DD: [Incident Title]

### Summary
[One sentence description]

### Timeline
- **HH:MM UTC:** [Event]
- **HH:MM UTC:** [Event]

### Affected Systems
| System | Impact |
|--------|--------|

### Root Cause
[Description]

### Impact
[Business impact]

### Actions Taken
1. [ ] Action 1
2. [ ] Action 2

### Lessons Learned
1. [Lesson]

### Prevention Measures
1. [Measure]
```
