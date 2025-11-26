# Phase 5: Performance Monitoring & Dashboards

**File:** `docs/predictions/operations/06-performance-monitoring.md`
**Created:** 2025-11-16
**Purpose:** Complete monitoring guide for Phase 5 prediction systems - CLI tools, SQL queries, dashboards, and alerting
**Status:** ✅ Production Ready

---

## 📋 Table of Contents

1. [Executive Summary](#executive-summary)
2. [Understanding Performance Metrics](#understanding-metrics)
3. [CLI Monitoring Tool](#cli-tool)
4. [Deep Dive SQL Queries](#sql-queries)
5. [Weekly Analysis](#weekly-analysis)
6. [Alerting Configuration](#alerting)
7. [What to Watch For](#what-to-watch)
8. [Future Enhancements](#future-enhancements)
9. [Related Documentation](#related-docs)

---

## 📊 Executive Summary {#executive-summary}

This guide shows you how to monitor your prediction systems daily using a simple CLI tool and SQL queries. You'll learn what metrics matter, how to spot problems early, and when to take action.

### Core Goal

Know every day if your systems are working well, catch issues before they cost money, and identify opportunities for improvement.

### What You'll Build

- **CLI monitoring tool** that runs in 10 seconds
- **Daily summary** sent to Slack/Email
- **SQL queries** for deep-dive analysis
- **Alerting** for critical issues

### Daily Workflow

```bash
# Morning routine (2 minutes)
python monitoring/performance_monitor.py --date yesterday

# Review summary, check for alerts
# If all green, you're done!
```

### Timeline

- **Day 1:** Set up CLI tool (1 hour)
- **Day 2:** Configure alerts (30 min)
- **Day 3+:** Run daily monitoring (2 min/day)

---

## 📈 Understanding Performance Metrics {#understanding-metrics}

### The 3 Metrics That Matter

#### 1. Over/Under Accuracy (Most Important for Profit)

**What it is:** % of times you correctly predicted OVER or UNDER

**Why it matters:** This is what wins bets. All other metrics support this.

**Calculation:**
```python
# For each prediction where you recommended OVER or UNDER
# Did the actual result match your recommendation?

Correct OVER/UNDER calls / Total recommendations = Accuracy
```

**What's good:**
- 🌟 **60%+** = Excellent (very profitable)
- ✅ **55-60%** = Good (profitable)
- ⚠️ **52-55%** = Marginal (barely profitable)
- ❌ **<52%** = Losing money

**Why 52% not 50%?** Betting vig (juice) means you need ~52.4% to break even.

**Example:**
```
100 predictions:
- 58 correct OVER/UNDER calls
- 42 incorrect calls
= 58% accuracy ✅ GOOD
```

---

#### 2. Mean Absolute Error (MAE) - Model Quality

**What it is:** Average difference between prediction and actual points

**Why it matters:** Shows if model understands player performance, not just guessing

**Calculation:**
```python
AVG(ABS(predicted_points - actual_points))
```

**What's good:**
- 🌟 **<4.0** = Excellent
- ✅ **4.0-4.5** = Good
- ⚠️ **4.5-5.0** = Acceptable
- ❌ **>5.0** = Needs improvement

**Example:**
```
Game 1: Predict 25, Actual 28 → Error 3
Game 2: Predict 22, Actual 19 → Error 3
Game 3: Predict 31, Actual 27 → Error 4
Average = (3+3+4)/3 = 3.3 MAE ✅ EXCELLENT
```

**Important:** Low MAE doesn't guarantee profit. A model with 4.2 MAE but 54% O/U accuracy makes money. A model with 3.8 MAE but 51% O/U accuracy loses money.

---

#### 3. Confidence Calibration - Trust Your Scores

**What it is:** Do high-confidence predictions actually perform better?

**Why it matters:** If not, your confidence scores are meaningless

**Calculation:**
```sql
-- For high confidence predictions (85+)
-- What's the actual accuracy?

SELECT
  CASE
    WHEN confidence_score >= 85 THEN 'HIGH'
    WHEN confidence_score >= 70 THEN 'MEDIUM'
    ELSE 'LOW'
  END as tier,
  AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) as accuracy
FROM prediction_results
GROUP BY tier
```

**What's good (well-calibrated):**
- HIGH confidence (85+): 65%+ accuracy ✅
- MEDIUM confidence (70+): 58%+ accuracy ✅
- LOW confidence (<70): 52%+ accuracy ✅

**Bad (poorly calibrated):**
- HIGH confidence: 55% accuracy ❌ (not better than medium!)
- MEDIUM confidence: 58% accuracy
- LOW confidence: 56% accuracy ❌ (almost as good as high!)

**What to do if poorly calibrated:**
- Adjust confidence thresholds (see [Confidence Scoring](../../algorithms/02-confidence-scoring-framework.md))
- Investigate high-confidence failures
- May need to retrain models (see [Continuous Retraining](../../ml-training/02-continuous-retraining.md))

---

### Secondary Metrics (Nice to Track)

#### Within 3 Points Rate
- % of predictions within 3 points of actual
- **Target:** 45%+
- Helps gauge precision

#### Recommendation Distribution
- How many OVER vs UNDER vs PASS?
- Should be somewhat balanced
- If 90% OVER, something's wrong

#### System Agreement
- When multiple systems agree, are they more accurate?
- **Target:** Yes (agreement = higher accuracy)

---

## 🛠️ CLI Monitoring Tool {#cli-tool}

### Tool Overview

**What it does:**
- Queries BigQuery for yesterday's results
- Calculates key metrics for each system
- Compares to baselines
- Identifies issues
- Sends summary via Slack/Email

**Run time:** ~10 seconds

### Implementation

Create: `monitoring/performance_monitor.py`

```python
"""
Daily Performance Monitor
Run this every morning to check system health
"""

import sys
from datetime import date, timedelta
from pathlib import Path
from google.cloud import bigquery
import pandas as pd
from tabulate import tabulate

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from notifications.notification_manager import send_notification

class PerformanceMonitor:
    """Monitor prediction system performance"""

    def __init__(self):
        self.bq_client = bigquery.Client()

        # Performance thresholds
        self.thresholds = {
            'ou_accuracy_excellent': 0.60,
            'ou_accuracy_good': 0.55,
            'ou_accuracy_minimum': 0.52,
            'mae_excellent': 4.0,
            'mae_good': 4.5,
            'mae_maximum': 5.0,
            'confidence_calibration_minimum': 0.10  # High conf should be 10% better than low
        }

    def run_daily_report(self, check_date=None):
        """
        Generate daily performance report

        Args:
            check_date: Date to check (default: yesterday)
        """
        if check_date is None:
            check_date = date.today() - timedelta(days=1)

        print("="*70)
        print(f" NBA PROPS DAILY PERFORMANCE REPORT")
        print(f" Date: {check_date}")
        print("="*70)

        # Get results
        results = self.get_daily_results(check_date)

        if results.empty:
            print(f"\n⚠️  No results found for {check_date}")
            print("   Games may not be complete yet, or no predictions were made.")
            return

        # Calculate metrics by system
        system_metrics = self.calculate_system_metrics(results)

        # Print summary
        self.print_summary(system_metrics, check_date)

        # Check for issues
        issues = self.identify_issues(system_metrics)

        # Send notification
        self.send_daily_notification(check_date, system_metrics, issues)

    def get_daily_results(self, check_date):
        """
        Get prediction results for a specific date
        """
        query = f"""
        SELECT
            r.system_id,
            s.system_name,
            s.system_type,
            s.is_champion,
            r.predicted_points,
            r.actual_points,
            r.predicted_recommendation,
            r.actual_result,
            r.prediction_correct,
            r.confidence_score,
            r.prediction_error,
            r.within_3_points,
            r.within_5_points,
            r.confidence_tier
        FROM `nba-props-platform.nba_predictions.prediction_results` r
        JOIN `nba-props-platform.nba_predictions.prediction_systems` s
            ON r.system_id = s.system_id
        WHERE r.game_date = '{check_date}'
            AND s.active = TRUE
            AND r.predicted_recommendation IN ('OVER', 'UNDER')  -- Exclude PASS
        """

        df = self.bq_client.query(query).to_dataframe()
        return df

    def calculate_system_metrics(self, df):
        """
        Calculate performance metrics for each system
        """
        metrics = []

        for system_id in df['system_id'].unique():
            system_df = df[df['system_id'] == system_id]

            # Basic info
            system_name = system_df['system_name'].iloc[0]
            system_type = system_df['system_type'].iloc[0]
            is_champion = system_df['is_champion'].iloc[0]

            # Core metrics
            total_predictions = len(system_df)
            ou_accuracy = system_df['prediction_correct'].mean()
            mae = system_df['prediction_error'].mean()
            within_3_rate = system_df['within_3_points'].mean()

            # Confidence metrics
            high_conf = system_df[system_df['confidence_score'] >= 85]
            high_conf_accuracy = high_conf['prediction_correct'].mean() if len(high_conf) > 0 else None

            low_conf = system_df[system_df['confidence_score'] < 70]
            low_conf_accuracy = low_conf['prediction_correct'].mean() if len(low_conf) > 0 else None

            # Calculate confidence calibration
            if high_conf_accuracy and low_conf_accuracy:
                confidence_calibration = high_conf_accuracy - low_conf_accuracy
            else:
                confidence_calibration = None

            # Recommendation breakdown
            over_count = len(system_df[system_df['predicted_recommendation'] == 'OVER'])
            under_count = len(system_df[system_df['predicted_recommendation'] == 'UNDER'])

            metrics.append({
                'system_id': system_id,
                'system_name': system_name,
                'system_type': system_type,
                'is_champion': is_champion,
                'total_predictions': total_predictions,
                'ou_accuracy': ou_accuracy,
                'mae': mae,
                'within_3_rate': within_3_rate,
                'high_conf_accuracy': high_conf_accuracy,
                'low_conf_accuracy': low_conf_accuracy,
                'confidence_calibration': confidence_calibration,
                'over_count': over_count,
                'under_count': under_count
            })

        return pd.DataFrame(metrics)

    def print_summary(self, metrics_df, check_date):
        """
        Print formatted summary table
        """
        print(f"\n📊 SYSTEM PERFORMANCE - {check_date}")
        print("-" * 70)

        # Prepare table data
        table_data = []

        for _, row in metrics_df.iterrows():
            # Format system name
            system_display = row['system_name']
            if row['is_champion']:
                system_display = f"👑 {system_display}"

            # Status emoji
            if row['ou_accuracy'] >= self.thresholds['ou_accuracy_excellent']:
                status = "🌟"
            elif row['ou_accuracy'] >= self.thresholds['ou_accuracy_good']:
                status = "✅"
            elif row['ou_accuracy'] >= self.thresholds['ou_accuracy_minimum']:
                status = "⚠️"
            else:
                status = "❌"

            table_data.append([
                status,
                system_display,
                row['total_predictions'],
                f"{row['ou_accuracy']:.1%}",
                f"{row['mae']:.2f}",
                f"{row['within_3_rate']:.1%}",
                f"{row['over_count']}/{row['under_count']}"
            ])

        headers = ['', 'System', 'Preds', 'O/U Acc', 'MAE', 'W/in 3', 'O/U']
        print(tabulate(table_data, headers=headers, tablefmt='simple'))

        print("\n📈 CONFIDENCE CALIBRATION")
        print("-" * 70)

        cal_table = []
        for _, row in metrics_df.iterrows():
            if row['confidence_calibration']:
                cal_status = "✅" if row['confidence_calibration'] > 0.10 else "⚠️"
                cal_table.append([
                    cal_status,
                    row['system_name'],
                    f"{row['high_conf_accuracy']:.1%}" if row['high_conf_accuracy'] else "N/A",
                    f"{row['low_conf_accuracy']:.1%}" if row['low_conf_accuracy'] else "N/A",
                    f"+{row['confidence_calibration']:.1%}" if row['confidence_calibration'] else "N/A"
                ])

        if cal_table:
            headers = ['', 'System', 'High Conf', 'Low Conf', 'Diff']
            print(tabulate(cal_table, headers=headers, tablefmt='simple'))
        else:
            print("  Not enough data for calibration analysis")

    def identify_issues(self, metrics_df):
        """
        Identify performance issues requiring attention
        """
        issues = []

        for _, row in metrics_df.iterrows():
            system = row['system_name']

            # Issue 1: Low O/U accuracy
            if row['ou_accuracy'] < self.thresholds['ou_accuracy_minimum']:
                issues.append({
                    'severity': 'HIGH',
                    'system': system,
                    'issue': f"O/U accuracy {row['ou_accuracy']:.1%} below minimum {self.thresholds['ou_accuracy_minimum']:.1%}",
                    'action': 'Investigate system, consider disabling'
                })

            # Issue 2: High MAE
            if row['mae'] > self.thresholds['mae_maximum']:
                issues.append({
                    'severity': 'MEDIUM',
                    'system': system,
                    'issue': f"MAE {row['mae']:.2f} above maximum {self.thresholds['mae_maximum']:.2f}",
                    'action': 'Check data quality, consider retraining'
                })

            # Issue 3: Poor confidence calibration
            if row['confidence_calibration'] and row['confidence_calibration'] < 0.05:
                issues.append({
                    'severity': 'LOW',
                    'system': system,
                    'issue': f"Confidence not calibrated (diff: {row['confidence_calibration']:.1%})",
                    'action': 'Review confidence scoring logic'
                })

            # Issue 4: Imbalanced recommendations
            total = row['over_count'] + row['under_count']
            over_pct = row['over_count'] / total if total > 0 else 0
            if over_pct > 0.75 or over_pct < 0.25:
                issues.append({
                    'severity': 'LOW',
                    'system': system,
                    'issue': f"Imbalanced: {row['over_count']} OVER, {row['under_count']} UNDER",
                    'action': 'Check if bias exists'
                })

        if issues:
            print(f"\n⚠️  ISSUES DETECTED ({len(issues)})")
            print("-" * 70)

            for i, issue in enumerate(issues, 1):
                severity_emoji = {
                    'HIGH': '🔴',
                    'MEDIUM': '🟡',
                    'LOW': '🟢'
                }[issue['severity']]

                print(f"{i}. {severity_emoji} {issue['severity']} - {issue['system']}")
                print(f"   Issue: {issue['issue']}")
                print(f"   Action: {issue['action']}\n")
        else:
            print(f"\n✅ NO ISSUES DETECTED - All systems performing well")

        return issues

    def send_daily_notification(self, check_date, metrics_df, issues):
        """
        Send daily summary via Slack/Email
        """
        # Overall summary
        total_predictions = metrics_df['total_predictions'].sum()
        avg_ou_accuracy = metrics_df['ou_accuracy'].mean()
        avg_mae = metrics_df['mae'].mean()

        # Champion performance
        champion = metrics_df[metrics_df['is_champion'] == True]
        if not champion.empty:
            champion_accuracy = champion['ou_accuracy'].iloc[0]
            champion_mae = champion['mae'].iloc[0]
        else:
            champion_accuracy = None
            champion_mae = None

        # Determine alert type
        if issues:
            high_severity = any(i['severity'] == 'HIGH' for i in issues)
            alert_type = 'error' if high_severity else 'warning'
        else:
            alert_type = 'info'

        # Format message
        message = f"""
📊 Daily Performance Report - {check_date}

🎯 OVERALL
  Total Predictions: {total_predictions}
  Avg O/U Accuracy: {avg_ou_accuracy:.1%}
  Avg MAE: {avg_mae:.2f}

👑 CHAMPION SYSTEM
  O/U Accuracy: {champion_accuracy:.1%} {self._get_emoji(champion_accuracy, 'accuracy')}
  MAE: {champion_mae:.2f} {self._get_emoji(champion_mae, 'mae')}

📋 SYSTEM BREAKDOWN
"""

        for _, row in metrics_df.iterrows():
            champion_marker = "👑 " if row['is_champion'] else "   "
            message += f"{champion_marker}{row['system_name']}: {row['ou_accuracy']:.1%} O/U, {row['mae']:.2f} MAE ({row['total_predictions']} preds)\n"

        if issues:
            message += f"\n⚠️  ISSUES ({len(issues)})\n"
            for issue in issues[:3]:  # Show top 3
                message += f"  • {issue['severity']}: {issue['issue']}\n"
        else:
            message += "\n✅ No issues detected"

        # Send notification
        send_notification(
            alert_type=alert_type,
            subject=f"Daily Performance Report - {check_date}",
            message=message,
            tags=['daily-report', 'performance']
        )

    def _get_emoji(self, value, metric_type):
        """Get status emoji for metric"""
        if metric_type == 'accuracy':
            if value >= 0.60:
                return "🌟"
            elif value >= 0.55:
                return "✅"
            elif value >= 0.52:
                return "⚠️"
            else:
                return "❌"
        elif metric_type == 'mae':
            if value < 4.0:
                return "🌟"
            elif value < 4.5:
                return "✅"
            elif value < 5.0:
                return "⚠️"
            else:
                return "❌"
        return ""


def main():
    """Run daily monitoring"""
    import argparse

    parser = argparse.ArgumentParser(description='Monitor prediction system performance')
    parser.add_argument('--date', type=str, default='yesterday',
                       help='Date to check (YYYY-MM-DD or "yesterday")')

    args = parser.parse_args()

    # Parse date
    if args.date == 'yesterday':
        check_date = date.today() - timedelta(days=1)
    elif args.date == 'today':
        check_date = date.today()
    else:
        check_date = date.fromisoformat(args.date)

    # Run monitor
    monitor = PerformanceMonitor()
    monitor.run_daily_report(check_date)


if __name__ == '__main__':
    main()
```

### Install Required Package

```bash
pip install tabulate  # For nice table formatting
pip freeze > requirements.txt
```

### Running the Monitor

**Daily command:**
```bash
# Check yesterday's results
python monitoring/performance_monitor.py --date yesterday

# Check specific date
python monitoring/performance_monitor.py --date 2025-01-19

# Check today (if games already complete)
python monitoring/performance_monitor.py --date today
```

### Sample Output

```
======================================================================
 NBA PROPS DAILY PERFORMANCE REPORT
 Date: 2025-01-19
======================================================================

📊 SYSTEM PERFORMANCE - 2025-01-19
----------------------------------------------------------------------
     System                           Preds    O/U Acc    MAE      W/in 3    O/U
🌟   👑 Ensemble Hybrid v1             47       61.7%      3.95     51.1%     24/23
✅   XGBoost All Features v1           47       58.5%      4.12     48.9%     25/22
✅   Similarity Balanced v1            47       57.4%      4.35     46.8%     26/21
⚠️   Similarity Fatigue Heavy v1      47       53.2%      4.68     42.6%     27/20

📈 CONFIDENCE CALIBRATION
----------------------------------------------------------------------
     System                     High Conf    Low Conf    Diff
✅   Ensemble Hybrid v1         68.2%        54.5%       +13.7%
✅   XGBoost All Features v1    65.0%        52.3%       +12.7%
⚠️   Similarity Balanced v1     59.1%        55.6%       +3.5%

⚠️  ISSUES DETECTED (2)
----------------------------------------------------------------------
1. 🟡 MEDIUM - Similarity Fatigue Heavy v1
   Issue: O/U accuracy 53.2% below target 55.0%
   Action: Monitor trend, may need weight adjustment

2. 🟢 LOW - Similarity Balanced v1
   Issue: Confidence not calibrated (diff: +3.5%)
   Action: Review confidence scoring logic

[Notification sent to Slack/Email]
```

---

## 🔍 Deep Dive SQL Queries {#sql-queries}

### Query 1: 7-Day Rolling Performance

**Purpose:** See performance trends over past week

```sql
-- 7-day performance by system
SELECT
  s.system_name,
  s.is_champion,
  r.game_date,
  COUNT(*) as predictions,
  AVG(CASE WHEN r.prediction_correct THEN 1.0 ELSE 0.0 END) as ou_accuracy,
  AVG(r.prediction_error) as mae,
  AVG(CASE WHEN r.within_3_points THEN 1.0 ELSE 0.0 END) as within_3_rate
FROM `nba-props-platform.nba_predictions.prediction_results` r
JOIN `nba-props-platform.nba_predictions.prediction_systems` s
  ON r.system_id = s.system_id
WHERE r.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND s.active = TRUE
  AND r.predicted_recommendation IN ('OVER', 'UNDER')
GROUP BY s.system_name, s.is_champion, r.game_date
ORDER BY r.game_date DESC, ou_accuracy DESC
```

**What to look for:**
- Is accuracy trending up or down?
- Are any systems consistently outperforming others?
- Big drops on specific dates? (investigate what happened)

---

### Query 2: System Comparison (Last 30 Days)

**Purpose:** Which system is best overall?

```sql
-- System leaderboard
SELECT
  s.system_name,
  s.system_type,
  s.is_champion,

  -- Volume
  COUNT(*) as total_predictions,

  -- Core metrics
  AVG(CASE WHEN r.prediction_correct THEN 1.0 ELSE 0.0 END) as ou_accuracy,
  AVG(r.prediction_error) as mae,
  AVG(CASE WHEN r.within_3_points THEN 1.0 ELSE 0.0 END) as within_3_rate,

  -- By recommendation type
  AVG(CASE WHEN r.predicted_recommendation = 'OVER' AND r.prediction_correct THEN 1.0
           WHEN r.predicted_recommendation = 'OVER' THEN 0.0 END) as over_accuracy,
  AVG(CASE WHEN r.predicted_recommendation = 'UNDER' AND r.prediction_correct THEN 1.0
           WHEN r.predicted_recommendation = 'UNDER' THEN 0.0 END) as under_accuracy,

  -- Confidence tiers
  AVG(CASE WHEN r.confidence_score >= 85 AND r.prediction_correct THEN 1.0
           WHEN r.confidence_score >= 85 THEN 0.0 END) as high_conf_accuracy

FROM `nba-props-platform.nba_predictions.prediction_results` r
JOIN `nba-props-platform.nba_predictions.prediction_systems` s
  ON r.system_id = s.system_id
WHERE r.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND s.active = TRUE
  AND r.predicted_recommendation IN ('OVER', 'UNDER')
GROUP BY s.system_name, s.system_type, s.is_champion
HAVING COUNT(*) >= 50  -- Minimum sample size
ORDER BY ou_accuracy DESC
```

**What to look for:**
- Should you change the champion?
- Are ML systems outperforming rule-based?
- Any system consistently worse? (consider disabling)

---

### Query 3: Failure Analysis

**Purpose:** Understand WHY predictions failed

```sql
-- Analyze biggest prediction errors
SELECT
  r.player_lookup,
  r.game_date,
  r.system_id,
  r.predicted_points,
  r.actual_points,
  r.prediction_error,
  r.confidence_score,
  r.fatigue_score,
  r.shot_zone_mismatch_score,
  r.similar_games_count,
  JSON_EXTRACT_SCALAR(r.key_factors, '$.extreme_fatigue') as extreme_fatigue,
  JSON_EXTRACT_SCALAR(r.key_factors, '$.paint_mismatch') as paint_mismatch
FROM `nba-props-platform.nba_predictions.prediction_results` r
WHERE r.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND r.prediction_error >= 8  -- 8+ point errors
ORDER BY r.prediction_error DESC
LIMIT 20
```

**What to look for:**
- Common patterns in big errors?
- High confidence failures? (especially concerning)
- Specific situations causing problems? (e.g., back-to-backs)

---

### Query 4: Confidence Calibration Deep Dive

**Purpose:** Is confidence score meaningful?

```sql
-- Confidence calibration by tier
SELECT
  s.system_name,
  CASE
    WHEN r.confidence_score >= 85 THEN 'VERY_HIGH'
    WHEN r.confidence_score >= 70 THEN 'HIGH'
    WHEN r.confidence_score >= 55 THEN 'MEDIUM'
    ELSE 'LOW'
  END as confidence_tier,

  COUNT(*) as predictions,
  AVG(r.confidence_score) as avg_confidence,
  AVG(CASE WHEN r.prediction_correct THEN 1.0 ELSE 0.0 END) as accuracy,
  AVG(r.prediction_error) as mae,

  -- Actual confidence vs expected
  AVG(r.confidence_score) - (AVG(CASE WHEN r.prediction_correct THEN 1.0 ELSE 0.0 END) * 100) as calibration_error

FROM `nba-props-platform.nba_predictions.prediction_results` r
JOIN `nba-props-platform.nba_predictions.prediction_systems` s
  ON r.system_id = s.system_id
WHERE r.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND s.active = TRUE
GROUP BY s.system_name, confidence_tier
ORDER BY s.system_name, MIN(r.confidence_score) DESC
```

**What good looks like:**
```
System: XGBoost v1
  VERY_HIGH (85+): 88 avg conf, 65% accuracy → Well calibrated
  HIGH (70-85):    76 avg conf, 58% accuracy → Well calibrated
  MEDIUM (55-70):  62 avg conf, 53% accuracy → Well calibrated
```

**What bad looks like:**
```
System: Similarity Balanced
  VERY_HIGH (85+): 88 avg conf, 54% accuracy → Overconfident!
  HIGH (70-85):    76 avg conf, 53% accuracy → Overconfident!
```

---

### Query 5: Player-Level Performance

**Purpose:** Which players are we good/bad at predicting?

```sql
-- Best and worst predicted players (min 10 games)
SELECT
  r.player_lookup,
  COUNT(*) as games_predicted,
  AVG(CASE WHEN r.prediction_correct THEN 1.0 ELSE 0.0 END) as ou_accuracy,
  AVG(r.prediction_error) as mae,
  AVG(r.actual_points) as avg_actual_points,

  -- Bias detection
  AVG(r.predicted_points - r.actual_points) as avg_bias  -- Positive = overpredicting

FROM `nba-props-platform.nba_predictions.prediction_results` r
WHERE r.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND r.system_id = (SELECT system_id FROM `nba-props-platform.nba_predictions.prediction_systems` WHERE is_champion = TRUE)
GROUP BY r.player_lookup
HAVING COUNT(*) >= 10
ORDER BY ou_accuracy DESC
LIMIT 50
```

**What to look for:**
- Consistently overpredicting certain players? (bias)
- Low accuracy on stars vs role players?
- Might need player-specific models (see [ML Training](../../ml-training/01-initial-model-training.md))

---

## 📅 Weekly Analysis {#weekly-analysis}

### Weekly Analysis Script

Create: `monitoring/weekly_analysis.py`

```python
"""
Weekly Deep Dive Analysis
Run every Monday to review last week's performance
"""

from google.cloud import bigquery
from datetime import date, timedelta
import pandas as pd
from tabulate import tabulate

class WeeklyAnalysis:
    """Weekly performance analysis"""

    def __init__(self):
        self.bq_client = bigquery.Client()

    def run_weekly_report(self):
        """Generate comprehensive weekly report"""

        # Last 7 days
        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=7)

        print("="*70)
        print(f" WEEKLY ANALYSIS: {start_date} to {end_date}")
        print("="*70)

        # 1. Overall Performance
        print("\n📊 OVERALL PERFORMANCE")
        print("-" * 70)
        self.print_overall_metrics(start_date, end_date)

        # 2. System Comparison
        print("\n🏆 SYSTEM LEADERBOARD")
        print("-" * 70)
        self.print_system_leaderboard(start_date, end_date)

        # 3. Confidence Analysis
        print("\n🎯 CONFIDENCE CALIBRATION")
        print("-" * 70)
        self.print_confidence_analysis(start_date, end_date)

        # 4. Biggest Wins/Losses
        print("\n📈 TOP WINS")
        print("-" * 70)
        self.print_top_predictions(start_date, end_date, best=True)

        print("\n📉 BIGGEST MISSES")
        print("-" * 70)
        self.print_top_predictions(start_date, end_date, best=False)

        # 5. Trends
        print("\n📈 PERFORMANCE TREND")
        print("-" * 70)
        self.print_daily_trend(start_date, end_date)

    # Additional methods would go here...


if __name__ == '__main__':
    analysis = WeeklyAnalysis()
    analysis.run_weekly_report()
```

**Run weekly:**
```bash
python monitoring/weekly_analysis.py
```

---

## 🚨 Alerting Configuration {#alerting}

### Alert Conditions

Create: `monitoring/alert_config.yaml`

```yaml
# Alert Configuration
# Defines when to send alerts

alerts:
  # HIGH priority - immediate action needed
  high_priority:
    - name: "Daily Accuracy Below Minimum"
      condition: "ou_accuracy < 0.52"
      cooldown_hours: 24
      message: "O/U accuracy fell below break-even threshold"

    - name: "MAE Spike"
      condition: "mae > previous_7_day_avg * 1.3"
      cooldown_hours: 12
      message: "MAE increased by 30%+ vs 7-day average"

    - name: "System Failure"
      condition: "predictions == 0 on game day"
      cooldown_hours: 1
      message: "No predictions generated for today's games"

  # MEDIUM priority - review within 24h
  medium_priority:
    - name: "Accuracy Decline"
      condition: "ou_accuracy < 0.55 for 3 consecutive days"
      cooldown_hours: 72
      message: "O/U accuracy below good threshold for 3 days"

    - name: "Confidence Miscalibration"
      condition: "high_conf_accuracy - low_conf_accuracy < 0.05"
      cooldown_hours: 168  # 1 week
      message: "Confidence scores not predictive"

  # LOW priority - review when convenient
  low_priority:
    - name: "Imbalanced Recommendations"
      condition: "over_pct > 0.75 OR over_pct < 0.25"
      cooldown_hours: 168
      message: "Recommendation distribution imbalanced"

    - name: "Low Sample Size"
      condition: "predictions < 20 on game day"
      cooldown_hours: 24
      message: "Fewer predictions than expected"

# Notification settings
notifications:
  high_priority:
    slack: true
    email: true

  medium_priority:
    slack: true
    email: false

  low_priority:
    slack: false
    email: true  # Daily digest
```

---

## 👀 What to Watch For {#what-to-watch}

### Daily Checklist (2 minutes)

**Every morning:**
```bash
python monitoring/performance_monitor.py --date yesterday
```

**Review:**
- ✅ **O/U Accuracy** - Is champion system >55%?
- ✅ **MAE** - Is it <4.5?
- ✅ **Issues** - Any red flags?
- ✅ **Volume** - Did all games get predictions?

**If all green** → Done! (30 seconds)
**If issues** → Investigate (10-30 minutes)

---

### Weekly Checklist (15 minutes)

**Every Monday:**
```bash
python monitoring/weekly_analysis.py
```

**Review:**
- **Trends** - Is performance improving or declining?
- **System comparison** - Should champion change?
- **Confidence calibration** - Are scores meaningful?
- **Pattern analysis** - Any systematic errors?

---

### Decision Frameworks

#### When to Disable a System
- O/U accuracy <52% for 7+ days
- Consistently worst performer
- Technical issues causing errors

#### When to Change Champion
- Challenger beats champion by 3%+ for 30 days
- Champion accuracy <55% for 14 days
- New ML model significantly outperforms

#### When to Retrain ML Model
- Production MAE > validation MAE + 1.0
- O/U accuracy drops >5% from baseline
- Feature importance shifts dramatically
- See [Continuous Retraining](../../ml-training/02-continuous-retraining.md) for details

#### When to Adjust Confidence Thresholds
- High confidence accuracy <60%
- Calibration error >10%
- Not enough high confidence predictions

---

## 🚀 Future Enhancements {#future-enhancements}

### Phase 2: Dashboard (When Ready)

**Looker Studio (Free)**
- Connect to BigQuery
- Daily/weekly/monthly views
- System comparison charts
- Automated email reports

**Dashboard panels:**
- Daily O/U accuracy line chart
- System comparison table
- Confidence calibration matrix
- Top performers/failures
- Trend analysis

---

### Phase 3: Advanced Monitoring

**Add later:**
- Real-time monitoring during games
- Profit/loss tracking (if betting)
- Market comparison (our line vs Vegas)
- Player-level performance tracking
- Situational analysis (home/away, B2B, etc.)

---

## 🔗 Related Documentation {#related-docs}

### Operations
- **[Daily Operations Checklist](./05-daily-operations-checklist.md)** - Morning routine and health checks
- **[Weekly Maintenance](./07-weekly-maintenance.md)** - Weekly review procedures
- **[Monthly Maintenance](./08-monthly-maintenance.md)** - Model retraining and monthly tasks
- **[Emergency Procedures](./09-emergency-procedures.md)** - Critical incident response
- **[Troubleshooting](../operations/03-troubleshooting.md)** - Common issues and solutions

### ML Training & Algorithms
- **[Initial Model Training](../../ml-training/01-initial-model-training.md)** - XGBoost training guide
- **[Continuous Retraining](../../ml-training/02-continuous-retraining.md)** - Drift detection and retraining
- **[Confidence Scoring Framework](../../algorithms/02-confidence-scoring-framework.md)** - How confidence is calculated

### Tutorials
- **[Getting Started](../../tutorials/01-getting-started.md)** - New operator onboarding
- **[Understanding Prediction Systems](../../tutorials/02-understanding-prediction-systems.md)** - System concepts

---

## 📝 Quick Reference

**Daily Command:**
```bash
python monitoring/performance_monitor.py --date yesterday
```

**Good Performance:**
- O/U Accuracy: 55%+
- MAE: <4.5
- Confidence calibrated

**Red Flags:**
- O/U Accuracy: <52%
- MAE: >5.0
- High conf = low conf accuracy

**When to Act:**
- Issues 3+ days in a row
- Sudden drops (>5%)
- Champion consistently underperforming

---

**Version:** 1.0
**Last Updated:** 2025-11-16
**Maintained By:** Platform Operations Team
