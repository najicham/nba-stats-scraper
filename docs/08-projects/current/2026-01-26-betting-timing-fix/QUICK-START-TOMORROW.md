# Quick Start: Tomorrow Morning Verification
## 2026-01-27 @ 10:00 AM ET - 5 Minute Check

---

## 🚀 Copy-Paste This (One Command)

```bash
cd ~/code/nba-stats-scraper && \
echo "=== 1. WORKFLOW START TIME ===" && \
grep "betting_lines.*RUN" logs/master_controller.log | grep "2026-01-27" | head -3 && \
echo -e "\n=== 2. BETTING DATA COUNT ===" && \
bq query --use_legacy_sql=false --format=csv "SELECT COUNT(*) as props, COUNT(DISTINCT game_id) as games FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\` WHERE game_date='2026-01-27'" && \
echo -e "\n=== 3. VALIDATION CHECK ===" && \
python scripts/validate_tonight_data.py --date 2026-01-27 2>&1 | grep -A 10 "SUMMARY"
```

**Expected Runtime**: 30 seconds

---

## ✅ Success Looks Like This

**1. Workflow Start Time**:
```
2026-01-27 08:XX:XX - betting_lines - Decision: RUN
```
✅ Started at 08:XX (not 13:XX)

**2. Betting Data Count**:
```
props,games
247,7
```
✅ 200-300 props, 7 games

**3. Validation Summary**:
```
SUMMARY
============================================================

✅ All checks passed!
```
✅ No errors, no false alarms

---

## ❌ Failure Looks Like This

**1. Workflow started at 1 PM** (not 8 AM):
```
2026-01-27 13:XX:XX - betting_lines - Decision: RUN
```
→ Config didn't reload, see "ROLLBACK" below

**2. Zero or partial data**:
```
props,games
0,0
```
→ Workflow didn't run or failed, check logs

**3. Validation has errors**:
```
❌ 5 ISSUES FOUND
```
→ Check which phase failed, investigate

---

## 🔧 If Something Failed

**Quick Fix - Restart Controller**:
```bash
systemctl restart nba-master-controller
# OR
pkill -f master_controller && python orchestration/master_controller.py &
```

**Check Config**:
```bash
grep window_before_game_hours config/workflows.yaml
# Expected: 12 (not 6)
```

**🚨 ROLLBACK (If Needed)**:
```bash
git revert f4385d03 && git push origin main
```

---

## 📋 Full Checklist

If you want details, see:
`docs/08-projects/current/2026-01-26-betting-timing-fix/TOMORROW-MORNING-CHECKLIST.md`

---

## 📊 Success = 3 Green Checks

- [ ] ✅ Workflow at 8 AM
- [ ] ✅ Betting data present (200-300 props, 7 games)
- [ ] ✅ Validation passes

**3/3 = SUCCESS 🎉**

---

## 📝 After Verification

**If Success**:
```bash
echo "2026-01-27: First production run SUCCESS ✅" >> docs/08-projects/current/2026-01-26-betting-timing-fix/PRODUCTION-RESULTS.md
```

**If Failure**:
```bash
echo "2026-01-27: First production run FAILED ❌ - [reason]" >> docs/08-projects/current/2026-01-26-betting-timing-fix/PRODUCTION-RESULTS.md
```

---

**That's it! 5 minutes, 3 checks, done.** ✅

See full docs if you need details or troubleshooting.
