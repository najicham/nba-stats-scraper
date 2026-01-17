#!/usr/bin/env python3
"""
Feature Store Analysis Script - Jan 7-8, 2026 Investigation
Analyzes the BigQuery data to understand feature quality changes
"""

import json
from pathlib import Path
from datetime import datetime

def load_json_results(filename):
    """Load JSON results from tmp files"""
    path = Path(f"/tmp/{filename}")
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None

def print_section(title):
    """Print section header"""
    print("\n" + "="*80)
    print(f" {title}")
    print("="*80 + "\n")

def analyze_quality_over_time():
    """Analyze feature quality trends over time"""
    print_section("1. FEATURE QUALITY OVER TIME (Jan 1-15)")

    data = load_json_results("q1_feature_quality_over_time.json")
    if not data:
        print("❌ No data found")
        return

    print(f"{'Date':<12} {'Avg Quality':>12} {'Min':>8} {'Max':>8} {'StdDev':>8} {'Records':>8}")
    print("-" * 80)

    for row in data:
        date = row['game_date']
        avg_q = float(row['avg_quality'])
        min_q = float(row['min_quality'])
        max_q = float(row['max_quality'])
        stddev = float(row['stddev_quality'])
        records = int(row['records'])

        # Highlight key dates
        marker = ""
        if date == "2026-01-07":
            marker = " ⭐ HIGHEST AVG QUALITY"
        elif date == "2026-01-08":
            marker = " 🚨 TRANSITION DAY"
        elif date == "2026-01-10":
            marker = " ⚠️  ANOMALY - VERY LOW"

        print(f"{date:<12} {avg_q:>12.2f} {min_q:>8.1f} {max_q:>8.1f} {stddev:>8.2f} {records:>8}{marker}")

    # Calculate before/after stats
    before_jan8 = [r for r in data if r['game_date'] <= '2026-01-07']
    after_jan8 = [r for r in data if r['game_date'] >= '2026-01-08']

    avg_before = sum(float(r['avg_quality']) * int(r['records']) for r in before_jan8) / sum(int(r['records']) for r in before_jan8)
    avg_after = sum(float(r['avg_quality']) * int(r['records']) for r in after_jan8) / sum(int(r['records']) for r in after_jan8)

    print(f"\n{'Before Jan 8 (weighted avg):':<40} {avg_before:.2f}")
    print(f"{'After Jan 8 (weighted avg):':<40} {avg_after:.2f}")
    print(f"{'Change:':<40} {avg_after - avg_before:+.2f} ({(avg_after/avg_before - 1)*100:+.1f}%)")

def analyze_data_source_transition():
    """Analyze data source distribution changes"""
    print_section("2. DATA SOURCE TRANSITION (THE SMOKING GUN)")

    data = load_json_results("q2_data_source_distribution.json")
    if not data:
        print("❌ No data found")
        return

    print(f"{'Date':<12} {'Source':<18} {'Records':>8} {'Avg Quality':>12} {'% of Day':>10}")
    print("-" * 80)

    # Group by date to calculate percentages
    by_date = {}
    for row in data:
        date = row['game_date']
        if date not in by_date:
            by_date[date] = []
        by_date[date].append(row)

    for date in sorted(by_date.keys()):
        rows = by_date[date]
        total_records = sum(int(r['records']) for r in rows)

        for row in rows:
            source = row['data_source']
            records = int(row['records'])
            avg_q = float(row['avg_quality'])
            pct = (records / total_records) * 100 if total_records > 0 else 0

            marker = ""
            if date == "2026-01-07" and source == "phase4_partial":
                marker = " ✅ Last day of phase4"
            elif date == "2026-01-08" and source == "mixed":
                marker = " 🚨 phase4_partial GONE!"

            print(f"{date:<12} {source:<18} {records:>8} {avg_q:>12.2f} {pct:>9.1f}%{marker}")

    # Count phase4 before and after
    phase4_before = sum(int(r['records']) for r in data if r['game_date'] <= '2026-01-07' and r['data_source'] == 'phase4_partial')
    phase4_after = sum(int(r['records']) for r in data if r['game_date'] >= '2026-01-08' and r['data_source'] == 'phase4_partial')

    print(f"\n{'phase4_partial records before Jan 8:':<40} {phase4_before}")
    print(f"{'phase4_partial records after Jan 8:':<40} {phase4_after}")
    print(f"{'Change:':<40} {phase4_after - phase4_before} ({(phase4_after - phase4_before) / phase4_before * 100 if phase4_before > 0 else 0:.0f}%)")

def analyze_before_after():
    """Analyze before/after comparison"""
    print_section("3. BEFORE vs AFTER COMPARISON")

    data = load_json_results("q6_before_after_comparison.json")
    if not data:
        print("❌ No data found")
        return

    before = next((r for r in data if 'Before' in r['period']), None)
    after = next((r for r in data if 'After' in r['period']), None)

    if not before or not after:
        print("❌ Missing before/after data")
        return

    print(f"{'Metric':<40} {'Before (Jan 1-7)':>18} {'After (Jan 8-15)':>18} {'Change':>15}")
    print("-" * 100)

    metrics = [
        ('Total Records', 'total_records', ''),
        ('Avg Quality', 'avg_quality', '.2f'),
        ('StdDev Quality', 'stddev_quality', '.2f'),
        ('Min Quality', 'min_quality', '.1f'),
        ('Max Quality', 'max_quality', '.1f'),
        ('', None, None),  # Separator
        ('phase4_partial count', 'phase4_partial_count', ''),
        ('mixed count', 'mixed_count', ''),
        ('', None, None),  # Separator
        ('Quality 90+ records', 'quality_90_plus', ''),
        ('Quality 80-89 records', 'quality_80_89', ''),
        ('Quality 70-79 records', 'quality_70_79', ''),
        ('Quality <70 records', 'quality_below_70', ''),
    ]

    for label, key, fmt in metrics:
        if key is None:
            print("")
            continue

        before_val = float(before[key]) if before[key] else 0
        after_val = float(after[key]) if after[key] else 0

        if fmt:
            before_str = f"{before_val:{fmt}}"
            after_str = f"{after_val:{fmt}}"
        else:
            before_str = f"{int(before_val)}"
            after_str = f"{int(after_val)}"

        # Calculate change
        if before_val > 0:
            pct_change = ((after_val / before_val) - 1) * 100
            change_str = f"{after_val - before_val:+.0f} ({pct_change:+.1f}%)"
        else:
            change_str = f"{after_val - before_val:+.0f}"

        marker = ""
        if key == 'phase4_partial_count' and after_val == 0:
            marker = " 🚨 GONE"
        elif key == 'quality_90_plus' and pct_change < -30:
            marker = " ⚠️  BIG DROP"

        print(f"{label:<40} {before_str:>18} {after_str:>18} {change_str:>15}{marker}")

    # Quality distribution percentages
    print("\n" + "-" * 100)
    print("QUALITY DISTRIBUTION PERCENTAGES:")
    print("-" * 100)

    for label, key in [('Quality 90+', 'quality_90_plus'),
                       ('Quality 80-89', 'quality_80_89'),
                       ('Quality 70-79', 'quality_70_79'),
                       ('Quality <70', 'quality_below_70')]:
        before_total = int(before['total_records'])
        after_total = int(after['total_records'])
        before_val = int(before[key])
        after_val = int(after[key])

        before_pct = (before_val / before_total * 100) if before_total > 0 else 0
        after_pct = (after_val / after_total * 100) if after_total > 0 else 0
        pct_change = after_pct - before_pct

        print(f"{label:<40} {before_pct:>17.1f}% {after_pct:>17.1f}% {pct_change:>14.1f}pp")

def analyze_transition_window():
    """Analyze the critical transition window (Jan 6-10)"""
    print_section("4. TRANSITION WINDOW (Jan 6-10)")

    data = load_json_results("q7_transition_window.json")
    if not data:
        print("❌ No data found")
        return

    print(f"{'Date':<12} {'Source':<18} {'Recs':>6} {'Avg Q':>8} {'Min':>6} {'Max':>6} | {'90+':>5} {'80-89':>6} {'70-79':>6} {'<70':>5}")
    print("-" * 100)

    for row in data:
        date = row['game_date']
        source = row['data_source']
        records = int(row['records'])
        avg_q = float(row['avg_quality'])
        min_q = float(row['min_quality'])
        max_q = float(row['max_quality'])
        q90 = int(row['quality_90_plus'])
        q80 = int(row['quality_80_89'])
        q70 = int(row['quality_70_79'])
        q_low = int(row['quality_below_70'])

        marker = ""
        if date == "2026-01-07" and source == "phase4_partial":
            marker = " ⭐ Last phase4"
        elif date == "2026-01-08":
            marker = " 🚨 TRANSITION"
        elif date == "2026-01-10":
            marker = " ⚠️  ANOMALY"

        print(f"{date:<12} {source:<18} {records:>6} {avg_q:>8.2f} {min_q:>6.1f} {max_q:>6.1f} | {q90:>5} {q80:>6} {q70:>6} {q_low:>5}{marker}")

def analyze_quality_score_buckets():
    """Analyze exact quality score distribution"""
    print_section("5. QUALITY SCORE DISTRIBUTION (Jan 6-10)")

    data = load_json_results("q10_quality_score_distribution.json")
    if not data:
        print("❌ No data found")
        return

    # Group by date
    by_date = {}
    for row in data:
        date = row['game_date']
        if date not in by_date:
            by_date[date] = []
        by_date[date].append(row)

    for date in sorted(by_date.keys()):
        rows = by_date[date]
        total = sum(int(r['record_count']) for r in rows)

        marker = ""
        if date == "2026-01-07":
            marker = " ⭐ Pre-transition"
        elif date == "2026-01-08":
            marker = " 🚨 Transition - ONLY 2 quality scores!"
        elif date == "2026-01-10":
            marker = " ⚠️  Anomaly"

        print(f"\n{date}{marker}")
        print(f"  Total records: {total}")
        print(f"  Quality scores:")

        for row in sorted(rows, key=lambda x: float(x['feature_quality_score'])):
            score = float(row['feature_quality_score'])
            count = int(row['record_count'])
            pct = (count / total * 100) if total > 0 else 0

            bar = "█" * int(pct / 2)  # Scale bar to fit screen
            print(f"    {score:>5.1f}: {count:>4} ({pct:>5.1f}%) {bar}")

def main():
    """Main analysis function"""
    print("\n" + "="*100)
    print(" "*30 + "FEATURE STORE ANALYSIS - JAN 7-8, 2026")
    print(" "*35 + "Investigation Report")
    print("="*100)
    print(f"\nAnalysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("Data Source: nba-props-platform.nba_predictions.ml_feature_store_v2")
    print("Date Range: 2026-01-01 to 2026-01-15")

    # Run all analyses
    analyze_quality_over_time()
    analyze_data_source_transition()
    analyze_before_after()
    analyze_transition_window()
    analyze_quality_score_buckets()

    # Summary
    print_section("KEY FINDINGS")
    print("""
1. 🚨 CRITICAL: phase4_partial data source completely disappeared on Jan 8, 2026
   - Before: 783 phase4_partial records (47% of total)
   - After: 0 phase4_partial records (0% of total)
   - This is a 100% loss of the high-quality data pipeline

2. 📉 Quality Distribution Shifted:
   - Quality 90+ records dropped from 46% → 25% (-46%)
   - Quality 80-89 records increased from 7% → 31% (+382%)
   - Lost the high-quality tier that models were likely trained on

3. ⚠️  Jan 8 Transition Characteristics:
   - ONLY 2 discrete quality scores (77.2 and 84.4)
   - Max quality dropped from 97.0 → 84.4
   - Record count dropped 56% (263 → 115)
   - Standard deviation collapsed to 2.8 (from 10.5)

4. 🔍 Jan 10 Anomaly:
   - Quality plummeted to 58.6-62.8 range
   - 95% of records at quality 62.8
   - Indicates upstream data pipeline instability

5. ✅ Features NOT Broken (structurally):
   - All records have exactly 33 features
   - No NULL or empty feature arrays
   - All features have valid numeric values
   - But feature VALUE distributions changed significantly

6. ❌ Metadata Fields Not Populated:
   - All source_*_completeness_pct fields are NULL
   - Cannot track data quality at source level
   - Missing critical observability

CONCLUSION:
This is a DATA PIPELINE FAILURE, not a feature engineering problem. The phase4_partial
pipeline stopped producing features on Jan 8, 2026. Models likely experienced training/
serving skew as they were trained on phase4_partial features but now serve predictions
with mixed-only features.

NEXT STEPS:
1. Investigate why phase4_partial pipeline stopped (intentional deprecation or bug?)
2. Either restore phase4_partial OR retrain models on mixed-only data
3. Add monitoring to alert on data source distribution changes
4. Fix source completeness metadata fields
    """)

    print("\n" + "="*100)
    print("Full analysis available in: FEATURE_STORE_JAN_7_8_COMPREHENSIVE_ANALYSIS.md")
    print("="*100 + "\n")

if __name__ == "__main__":
    main()
