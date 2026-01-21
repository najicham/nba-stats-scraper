# Activate Scheduled Query - Quick Guide

**Time**: 5 minutes
**File to copy**: `schemas/bigquery/nba_predictions/SCHEDULED_QUERY_READY.sql`

---

## Steps

### 1. Open BigQuery Console
Go to: https://console.cloud.google.com/bigquery?project=nba-props-platform

### 2. Click "Scheduled Queries"
- In the left navigation, find **"Scheduled queries"**
- Click it

### 3. Click "CREATE SCHEDULED QUERY"
Big blue button at the top

### 4. Paste the Query
- Copy ALL contents from: `schemas/bigquery/nba_predictions/SCHEDULED_QUERY_READY.sql`
- Paste into the query editor
- The query is 124 lines - make sure you got it all

### 5. Configure Schedule

**New scheduled query form**:

**Name**: `nba-prediction-grading-daily`

**Schedule options**:
- **Repeats**: `Daily`
- **Start date**: Today's date (2026-01-17)
- **Start time (hour and minute)**: `12:00 PM`
- **Timezone**: `America/Los_Angeles` (Pacific Time)

**Destination for query results**:
- Leave as **"No destination table"**
- (Query handles INSERT itself)

**Advanced options** (optional):
- **Email notifications**: Add your email if you want failure alerts
- **Retry on failure**: Leave default (3 retries)

### 6. Click "SAVE"

### 7. Verify It's Created

You should see:
```
✓ nba-prediction-grading-daily
  Schedule: Daily at 12:00 PM
  State: ENABLED
  Next run: Tomorrow at 12:00 PM PT
```

---

## Test It (Optional)

**Run it now manually**:
1. Find your scheduled query in the list
2. Click the **⋮** (three dots) menu
3. Click **"Run now"**
4. Wait ~5 seconds
5. Check results:
   ```sql
   SELECT COUNT(*) FROM `nba-props-platform.nba_predictions.prediction_grades`
   WHERE game_date = CURRENT_DATE();
   ```

---

## Troubleshooting

**"Permission denied" error**:
- Make sure you're in project `nba-props-platform`
- Check you have BigQuery Admin role

**Query syntax error**:
- Make sure you copied the ENTIRE query (124 lines)
- Check no extra characters at start/end

**Can't find "Scheduled queries"**:
- Make sure you're in BigQuery (not Cloud Console)
- Look in left nav under "BigQuery" section

---

## You're Done!

✅ Scheduled query active
✅ Will run daily at noon PT
✅ Fully automated grading enabled

Tomorrow at 12:30 PM PT, you'll get your first Slack alert (if any issues).
