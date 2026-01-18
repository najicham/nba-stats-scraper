# NBA Stats Scraper - Project Reminders

## XGBoost V1 Production Monitoring Schedule

### 📅 2026-01-24 (7 days) - Initial Performance Check
**Status:** ⏳ Pending

**What to check:**
- Run daily performance query from `XGBOOST-V1-PERFORMANCE-GUIDE.md`
- Verify production MAE is close to validation baseline (3.98)
- Check for any placeholders (should be 0)
- Verify prediction volume is consistent

**Success criteria:**
- Production MAE ≤ 4.5 (target)
- Ideally MAE ≤ 4.5 (within validation range)
- Win rate ≥ 52.4% (breakeven)
- No placeholders

**Query to run:**
```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as production_mae
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE system_id = 'xgboost_v1'
  AND game_date >= '2026-01-17'
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
"
```

**Time required:** 30-60 minutes

---

### 📅 2026-01-31 (14 days) - Head-to-Head Comparison Start
**Status:** ⏳ Pending

**What to check:**
- Run head-to-head comparison queries (XGBoost V1 vs CatBoost V8)
- Compare MAE, win rate, confidence calibration
- Analyze prediction agreement/disagreement patterns
- Identify performance patterns (OVER vs UNDER, confidence tiers)

**Success criteria:**
- Sufficient sample size (100+ overlapping picks)
- Clear performance trends emerging
- Statistical significance in differences

**Reference document:**
`/home/naji/code/nba-stats-scraper/docs/08-projects/current/ml-model-v8-deployment/XGBOOST-V1-PERFORMANCE-GUIDE.md`

**Time required:** 1-2 hours

---

### 📅 2026-02-16 (30 days) - Champion Decision Point
**Status:** ⏳ Pending

**What to decide:**
- **Option A:** Promote XGBoost V1 to champion (if production MAE < 3.40)
- **Option B:** Keep both active (if MAE 3.40-4.0)
- **Option C:** Demote/retrain XGBoost V1 (if MAE > 4.5)
- **Option D:** Add confidence filtering (if problem tiers identified)

**Analysis required:**
- 30-day production performance summary
- Confidence tier breakdown (identify weak tiers like CatBoost's 88-90%)
- Head-to-head win rate comparison
- Business impact analysis

**Success criteria for promotion:**
- Production MAE < 3.40 for 30+ consecutive days
- Win rate > CatBoost V8
- No critical confidence tier issues
- Stable prediction volume

**Time required:** 2-3 hours

---

## Future Milestones

### 📅 2026-03-17 (60 days) - Ensemble Optimization
**What to do:**
- Collect 60 days of XGBoost V1 + CatBoost V8 data
- Optimize ensemble weights (test 60/40, 50/50, 70/30)
- Analyze if ensemble MAE < best individual model

**Reference:** `FUTURE-ENHANCEMENTS-ROADMAP.md` - Month 1 section

---

### 📅 2026-04-17 (Q1 End) - Quarterly Retrain
**What to do:**
- Retrain models with Q1 2026 data
- Update feature importance analysis
- Deploy new model versions if performance improves

**Reference:** `FUTURE-ENHANCEMENTS-ROADMAP.md` - Q1 2026 section

---

## How to Use This File

1. **Check this file periodically** or set up reminders (see below)
2. **Mark items complete** by changing ⏳ to ✅ when done
3. **Add notes** under each section as you complete tasks
4. **Update SUCCESS/FAILURE** status based on results

---

## Automated Reminder System (✅ ACTIVE)

**Status:** ✅ Configured and running daily at 9:00 AM

**What's Set Up:**
1. ✅ Daily cron job checks for reminder dates
2. ✅ Desktop notifications (if available)
3. ✅ **Slack notifications to #reminders** (dedicated channel)
4. ✅ Console output with full details
5. ✅ Logging to `reminder-log.txt`

**Reminder Dates:**
- **2026-01-24** (7 days): XGBoost V1 Initial Performance Check
- **2026-01-31** (14 days): Head-to-Head Comparison Start
- **2026-02-16** (30 days): Champion Decision Point
- **2026-03-17** (60 days): Ensemble Optimization
- **2026-04-17** (Q1 end): Quarterly Retrain

---

### Testing & Verification

**Test Slack notifications:**
```bash
cd ~/code/nba-stats-scraper
export $(grep -v '^#' .env | xargs)
~/bin/test-slack-reminder.py
```

**View scheduled cron job:**
```bash
crontab -l | grep nba-reminder
```

**Check reminder logs:**
```bash
tail -f ~/code/nba-stats-scraper/reminder-log.txt
```

**Manually trigger reminder (for testing):**
```bash
~/bin/nba-reminder.sh
```

---

### How It Works

**Daily at 9:00 AM:**
1. Cron runs `~/bin/nba-reminder.sh`
2. Bash script checks if today matches a reminder date
3. If match found:
   - Sends desktop notification (if `notify-send` available)
   - Sources `.env` and calls `~/bin/nba-slack-reminder.py`
   - Python script sends rich formatted message to Slack
   - Prints details to console
   - Logs to `reminder-log.txt`

**Slack Message Format:**
- 📋 Header with reminder title
- ✅ Priority and time estimate
- 📝 Task checklist
- 🎯 Success criteria
- 📚 Link to full documentation

---

### Troubleshooting

**Slack not working?**
```bash
# Verify webhook URL is set
echo $SLACK_WEBHOOK_URL_REMINDERS

# If empty, source .env file
export $(grep -v '^#' ~/code/nba-stats-scraper/.env | xargs)

# Test again
~/bin/test-slack-reminder.py
```

**Cron not running?**
```bash
# Check cron service status
systemctl status cron

# View cron logs
grep CRON /var/log/syslog | tail -20

# Verify crontab entry
crontab -l
```

**Desktop notifications not working?**
```bash
# Check if notify-send is available
which notify-send

# Install if missing (Ubuntu/Debian)
sudo apt-get install libnotify-bin
```

---

### Manual Setup (If Needed)

If you need to set this up again or on a different machine:

```bash
# 1. Ensure scripts are executable
chmod +x ~/bin/nba-reminder.sh
chmod +x ~/bin/nba-slack-reminder.py
chmod +x ~/bin/test-slack-reminder.py

# 2. Add cron job (if not already present)
(crontab -l 2>/dev/null; echo "0 9 * * * $HOME/bin/nba-reminder.sh") | crontab -

# 3. Verify .env has SLACK_WEBHOOK_URL_REMINDERS
grep SLACK_WEBHOOK_URL_REMINDERS ~/code/nba-stats-scraper/.env

# 4. Test the system
cd ~/code/nba-stats-scraper
export $(grep -v '^#' .env | xargs)
~/bin/test-slack-reminder.py
```

---

**Last Updated:** 2026-01-17
**Created by:** Session 94
