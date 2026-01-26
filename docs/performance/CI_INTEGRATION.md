# Performance Testing CI/CD Integration

This document describes how performance benchmarks are integrated into the CI/CD pipeline for regression detection and deployment gating.

## Overview

Performance tests run automatically at key points in the development lifecycle:
1. **Pull Requests**: Compare against main branch baseline
2. **Main Branch**: Track performance trends over time
3. **Pre-deployment**: Gate deployments on performance regression

## CI/CD Pipeline Integration

### GitHub Actions Workflow

Create `.github/workflows/performance.yml`:

```yaml
name: Performance Benchmarks

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
  schedule:
    # Run nightly at 2 AM UTC
    - cron: '0 2 * * *'
  workflow_dispatch:

jobs:
  benchmark:
    runs-on: ubuntu-latest
    timeout-minutes: 30

    steps:
      - name: Checkout code
        uses: actions/checkout@v3
        with:
          fetch-depth: 0  # Fetch all history for comparison

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r requirements-performance.txt

      - name: Download baseline benchmarks
        uses: actions/cache@v3
        with:
          path: .benchmarks
          key: benchmarks-${{ github.ref }}-${{ github.sha }}
          restore-keys: |
            benchmarks-${{ github.ref }}-
            benchmarks-main-

      - name: Run performance benchmarks
        run: |
          pytest tests/performance/ \
            --benchmark-only \
            --benchmark-autosave \
            --benchmark-save=pr-${{ github.event.pull_request.number || 'main' }} \
            --benchmark-compare-fail=mean:20% \
            --benchmark-columns=min,max,mean,stddev \
            -v

      - name: Upload benchmark results
        uses: actions/upload-artifact@v3
        if: always()
        with:
          name: benchmark-results
          path: .benchmarks/

      - name: Comment PR with results
        if: github.event_name == 'pull_request'
        uses: actions/github-script@v6
        with:
          script: |
            const fs = require('fs');
            const benchmarkData = fs.readFileSync('.benchmarks/latest.json', 'utf8');
            const results = JSON.parse(benchmarkData);

            let comment = '## Performance Benchmark Results\n\n';
            comment += '| Test | Mean Time | Baseline | Change |\n';
            comment += '|------|-----------|----------|--------|\n';

            // Format results (simplified)
            results.benchmarks.forEach(bench => {
              comment += `| ${bench.name} | ${bench.stats.mean}s | - | - |\n`;
            });

            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: comment
            });

      - name: Fail on regression
        if: failure()
        run: |
          echo "Performance regression detected!"
          echo "Review benchmark results and optimize before merging."
          exit 1
```

### Cloud Build Configuration

For Google Cloud Build, create `cloudbuild-performance.yaml`:

```yaml
steps:
  # Set up Python environment
  - name: 'python:3.11'
    id: 'install-deps'
    entrypoint: 'pip'
    args:
      - 'install'
      - '-r'
      - 'requirements.txt'
      - '-r'
      - 'requirements-performance.txt'

  # Run performance benchmarks
  - name: 'python:3.11'
    id: 'run-benchmarks'
    entrypoint: 'pytest'
    args:
      - 'tests/performance/'
      - '--benchmark-only'
      - '--benchmark-autosave'
      - '--benchmark-save=build-$BUILD_ID'
      - '--benchmark-compare-fail=mean:20%'
      - '-v'

  # Upload results to GCS
  - name: 'gcr.io/cloud-builders/gsutil'
    id: 'upload-results'
    args:
      - 'cp'
      - '-r'
      - '.benchmarks/*'
      - 'gs://${_BENCHMARK_BUCKET}/benchmarks/$BUILD_ID/'

  # Check for regressions
  - name: 'python:3.11'
    id: 'check-regressions'
    entrypoint: 'python'
    args:
      - 'scripts/check_performance_regression.py'
      - '--threshold=20'
      - '--fail-on-regression'

timeout: '1800s'  # 30 minutes

substitutions:
  _BENCHMARK_BUCKET: 'nba-stats-benchmarks'

options:
  machineType: 'N1_HIGHCPU_8'  # Consistent machine for benchmarks
```

## Regression Detection

### Detection Thresholds

Performance regressions trigger different actions based on severity:

| Severity | Threshold | Action |
|----------|-----------|--------|
| **Warning** | +20% latency<br>-10% throughput | Comment on PR<br>Request review |
| **Critical** | +50% latency<br>-25% throughput | Block merge<br>Require fixes |
| **Severe** | +100% latency<br>-50% throughput | Alert team<br>Immediate investigation |

### Regression Check Script

Create `scripts/check_performance_regression.py`:

```python
#!/usr/bin/env python3
"""
Check for performance regressions in benchmark results.

Usage:
    python scripts/check_performance_regression.py --threshold=20
"""

import json
import sys
import argparse
from pathlib import Path

def load_benchmark(filepath):
    """Load benchmark JSON file."""
    with open(filepath) as f:
        return json.load(f)

def compare_benchmarks(baseline, current, threshold_pct):
    """Compare benchmarks and detect regressions."""
    regressions = []

    baseline_map = {b['name']: b for b in baseline['benchmarks']}

    for bench in current['benchmarks']:
        name = bench['name']
        if name not in baseline_map:
            continue

        baseline_mean = baseline_map[name]['stats']['mean']
        current_mean = bench['stats']['mean']

        pct_change = ((current_mean - baseline_mean) / baseline_mean) * 100

        if pct_change > threshold_pct:
            regressions.append({
                'name': name,
                'baseline': baseline_mean,
                'current': current_mean,
                'change_pct': pct_change
            })

    return regressions

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', default='.benchmarks/baseline.json')
    parser.add_argument('--current', default='.benchmarks/latest.json')
    parser.add_argument('--threshold', type=float, default=20.0)
    parser.add_argument('--fail-on-regression', action='store_true')
    args = parser.parse_args()

    baseline = load_benchmark(args.baseline)
    current = load_benchmark(args.current)

    regressions = compare_benchmarks(baseline, current, args.threshold)

    if regressions:
        print(f"❌ Performance Regressions Detected ({len(regressions)}):")
        print()
        for reg in regressions:
            print(f"  {reg['name']}")
            print(f"    Baseline: {reg['baseline']:.3f}s")
            print(f"    Current:  {reg['current']:.3f}s")
            print(f"    Change:   +{reg['change_pct']:.1f}%")
            print()

        if args.fail_on_regression:
            sys.exit(1)
    else:
        print("✅ No performance regressions detected")

if __name__ == '__main__':
    main()
```

## Deployment Gating

### Pre-deployment Checks

Before deploying to production:

```bash
# Run benchmarks
pytest tests/performance/ --benchmark-only --benchmark-autosave

# Compare with production baseline
pytest tests/performance/ \
  --benchmark-compare=production-baseline \
  --benchmark-compare-fail=mean:10%

# Check for critical regressions
python scripts/check_performance_regression.py \
  --baseline=.benchmarks/production-baseline.json \
  --threshold=10 \
  --fail-on-regression
```

If benchmarks fail, deployment is blocked until:
1. Performance is optimized to meet targets
2. Regression is investigated and approved
3. Baseline is updated with new expected performance

### Deployment Pipeline Integration

```bash
#!/bin/bash
# deploy.sh with performance gate

set -e

echo "Running pre-deployment performance checks..."

# Run benchmarks
./scripts/run_benchmarks.sh --compare

# Check for regressions
python scripts/check_performance_regression.py \
  --threshold=10 \
  --fail-on-regression

if [ $? -ne 0 ]; then
  echo "❌ Performance regression detected - blocking deployment"
  exit 1
fi

echo "✅ Performance checks passed"

# Proceed with deployment
gcloud run deploy ...
```

## Baseline Management

### Establishing Baselines

**Initial baseline:**
```bash
# Run on stable main branch
pytest tests/performance/ \
  --benchmark-save=baseline-v1.0 \
  --benchmark-autosave
```

**Production baseline:**
```bash
# After successful deployment
pytest tests/performance/ \
  --benchmark-save=production-baseline \
  --benchmark-autosave
```

### Updating Baselines

Update baselines after approved performance changes:

```bash
# After optimization
pytest tests/performance/ --benchmark-autosave

# Verify improvement
pytest tests/performance/ --benchmark-compare=baseline

# If improved, save as new baseline
mv .benchmarks/latest.json .benchmarks/baseline.json
```

### Baseline Storage

Store baselines in version control:

```bash
# .gitignore
.benchmarks/*.json
!.benchmarks/baseline.json
!.benchmarks/production-baseline.json
```

Or store in GCS for team access:

```bash
# Upload baseline
gsutil cp .benchmarks/baseline.json \
  gs://nba-stats-benchmarks/baselines/baseline-$(date +%Y%m%d).json

# Download baseline
gsutil cp gs://nba-stats-benchmarks/baselines/baseline-latest.json \
  .benchmarks/baseline.json
```

## Performance Monitoring

### Trend Tracking

Track performance trends over time:

```python
# scripts/track_performance_trends.py
import json
import pandas as pd
import matplotlib.pyplot as plt

def load_benchmarks(directory):
    """Load all benchmark files and create DataFrame."""
    benchmarks = []
    for path in Path(directory).glob('*.json'):
        with open(path) as f:
            data = json.load(f)
            for bench in data['benchmarks']:
                benchmarks.append({
                    'date': data['datetime'],
                    'name': bench['name'],
                    'mean': bench['stats']['mean'],
                    'stddev': bench['stats']['stddev']
                })
    return pd.DataFrame(benchmarks)

def plot_trends(df, output_file='performance_trends.png'):
    """Plot performance trends over time."""
    fig, ax = plt.subplots(figsize=(12, 6))

    for name in df['name'].unique():
        data = df[df['name'] == name]
        ax.plot(data['date'], data['mean'], label=name, marker='o')

    ax.set_xlabel('Date')
    ax.set_ylabel('Mean Time (seconds)')
    ax.set_title('Performance Trends')
    ax.legend()
    ax.grid(True)

    plt.savefig(output_file)
```

### Alerting

Set up alerts for performance degradation:

```yaml
# monitoring/alerts/performance.yaml
alerts:
  - name: PerformanceDegradation
    condition: |
      benchmark_mean_seconds > baseline_mean_seconds * 1.5
    for: 2 consecutive runs
    severity: warning
    notification:
      - slack: #alerts-performance
      - email: team@example.com
```

## Best Practices

### CI/CD Integration

1. **Run on consistent hardware**: Use same machine type for comparable results
2. **Warm up before benchmarking**: Run warmup iterations
3. **Isolate from other jobs**: Don't run other CPU-intensive tasks
4. **Cache dependencies**: Speed up CI runs
5. **Fail fast**: Stop on critical regressions

### Baseline Management

1. **Version baselines**: Track baseline changes over time
2. **Document updates**: Explain why baseline changed
3. **Review before updating**: Don't blindly accept regressions
4. **Store securely**: Use version control or GCS
5. **Separate prod/dev**: Different baselines for different environments

### Regression Detection

1. **Set appropriate thresholds**: 20% warning, 50% critical
2. **Review all regressions**: Even small ones add up
3. **Investigate root causes**: Don't just update baseline
4. **Track trends**: Look for gradual degradation
5. **Alert on severe regressions**: Immediate team notification

### Performance Culture

1. **Make it visible**: Dashboard with performance trends
2. **Celebrate improvements**: Recognize optimization work
3. **Block bad PRs**: Don't merge performance regressions
4. **Automate checks**: Make it part of standard workflow
5. **Continuous improvement**: Regular performance review

---

**Document Version:** 1.0
**Last Updated:** 2026-01-25
