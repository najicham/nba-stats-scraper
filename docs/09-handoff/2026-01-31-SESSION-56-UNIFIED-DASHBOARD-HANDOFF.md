# Session 56 Handoff - Unified Dashboard Design & Implementation Plan

**Date:** 2026-01-31
**Session Focus:** Unified admin dashboard design from scratch
**Status:** ✅ Research complete, ready for implementation
**Next Session Goal:** Begin building the unified dashboard

---

## Executive Summary

This session completed comprehensive research and design for a **unified admin dashboard** that consolidates all monitoring, operations, and analytics into a single interface. The dashboard will replace 3 fragmented systems (2 Cloud Function dashboards + existing admin dashboard) with one cohesive solution.

**Key Achievement:** 6 parallel agent investigations covering:
1. Dashboard design patterns and user workflows
2. Prediction quality and ML performance visualization
3. Real-time pipeline operations monitoring
4. Data quality intelligence and trust scoring
5. Cost optimization and efficiency analytics
6. Innovative features (AI-powered debugging, NL queries, etc.)

**Status:** Design complete, architecture defined, ready to build

---

## Table of Contents

1. [Background & Context](#background--context)
2. [Current State Assessment](#current-state-assessment)
3. [Proposed Solution: 8-Page Unified Dashboard](#proposed-solution-8-page-unified-dashboard)
4. [Technical Architecture](#technical-architecture)
5. [Design System & UX](#design-system--ux)
6. [Implementation Roadmap](#implementation-roadmap)
7. [Key Research Findings](#key-research-findings)
8. [Agent Investigation Results](#agent-investigation-results)
9. [Files & References](#files--references)
10. [Next Steps for New Session](#next-steps-for-new-session)

---

## Background & Context

### The Problem

**User request:** "Merge all dashboards into one, think from scratch, use white theme"

The NBA Stats Scraper project has **fragmented monitoring** across multiple systems:

1. **Pipeline Dashboard** (Cloud Function) - `/orchestration/cloud_functions/pipeline_dashboard/`
   - Shows processor runs, heartbeats, prediction coverage
   - Dark theme (#1a1a2e background)
   - Auto-refresh every 60 seconds
   - Recently added: Shot zone quality monitoring (Session 54)

2. **Scraper Dashboard** (Cloud Function) - `/orchestration/cloud_functions/scraper_dashboard/`
   - Shows scraper gaps, proxy health, circuit breakers
   - White theme (#f5f5f5 background) ← **User prefers this**
   - Auto-refresh every 60 seconds

3. **Admin Dashboard Service** (Flask app) - `/services/admin_dashboard/`
   - Comprehensive monitoring with 13 blueprints
   - Status, data quality, source blocks, actions, analytics, costs, trends, reliability, audit, grading, latency, league trends, partials
   - API key authentication
   - Prometheus metrics export
   - **Most sophisticated but possibly underutilized**

### The Opportunity

Rather than patch existing systems, **design the ideal dashboard from scratch** considering:
- User workflows (what questions do ops teams ask daily?)
- Industry best practices (Datadog, Grafana patterns)
- Business value (predictions, ROI, model health)
- Operational efficiency (one-click remediation, AI-assisted debugging)

---

## Current State Assessment

### What We Have (Infrastructure)

**Excellent monitoring foundation:**
- 40+ Cloud Functions for alerts and monitoring
- BigQuery tables tracking every aspect of the system
- Firestore for real-time state (processor heartbeats, phase completions)
- Cloud Monitoring integration
- Comprehensive logging

**Key data sources:**
- `nba_predictions.prediction_accuracy` - 419K+ records (grading results)
- `nba_predictions.ml_feature_store_v2` - Feature health tracking
- `nba_reference.processor_run_history` - All processor executions
- `nba_orchestration.*` - Phase transitions, circuit breakers, data gaps
- Firestore collections: `processor_heartbeats`, `phase2_completion`, `phase3_completion`

**Monitoring capabilities:**
- Data quality alerts (6 checks: zero predictions, usage rate, duplicates, prop lines, BDL quality, shot zones)
- BDB critical monitor (shot zone data availability)
- DLQ monitoring
- Prediction health alerts
- Model drift detection (script exists: `bin/monitoring/model_drift_detection.py`)

### What's Missing (Gaps)

**Fragmentation issues:**
- No single source of truth for system health
- No unified navigation between monitoring areas
- Inconsistent design (dark vs white theme)
- Missing key visualizations:
  - Prediction accuracy trends (90-day)
  - ROI performance by system
  - Model confidence calibration
  - Cost per prediction tracking
  - BDL readiness status
  - Shot zone quality trends (table exists but not visualized)

**Workflow pain points:**
- Engineers run 40+ manual BigQuery queries daily
- Incident investigation requires jumping between 5+ tools
- Deployment impact not tracked or visualized
- No predictive alerting (only reactive)
- Root cause analysis takes 30-90 minutes

---

## Proposed Solution: 8-Page Unified Dashboard

### Overall Design Philosophy

**3-Layer Information Hierarchy:**
```
Layer 1: "Blink Status" (3 seconds to assess)
  ↓ One health score + critical alerts

Layer 2: "Deep Dive" (2-3 minutes)
  ↓ Phase breakdowns, metric trends

Layer 3: "Investigation" (5-10 minutes)
  ↓ Raw logs, correlation traces, historical analysis
```

### Page Structure

#### **Page 1: HOME / COMMAND CENTER** ⭐ Primary Landing

**Purpose:** See entire system health in 3 seconds

**Key Sections:**
```
┌─────────────────────────────────────────────────────────┐
│ SYSTEM HEALTH: 🟢 89/100                               │
│ Status: HEALTHY (with warnings)                        │
├─────────────────────────────────────────────────────────┤
│ ┌──────────┬──────────┬──────────┬──────────┬─────────┐│
│ │Pipeline  │Data      │ML Ops    │Services  │Costs    ││
│ │95/100 ✅ │87/100 🟡 │72/100 🟡 │98/100 ✅ │NORMAL ✅││
│ └──────────┴──────────┴──────────┴──────────┴─────────┘│
│                                                          │
│ 🔴 CRITICAL ALERTS (3)              QUICK ACTIONS       │
│  • DLQ: 23 messages (Phase 4)       [Replay DLQ]       │
│  • Shot zones 40% incomplete        [Trigger Backfill] │
│  • Model calibration low (68%)      [View Details]     │
│                                                          │
│ TODAY'S SUMMARY                                         │
│  Games Processed: 10/10 ✅                              │
│  Predictions Made: 485 (98.0% coverage)                │
│  Predictions Graded: 240/240 (100%)                    │
│  Avg Accuracy: 56.2% (↑ 2.1% vs 7-day avg)            │
│                                                          │
│ PIPELINE FLOW (Animated)                                │
│  Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → P6 │
│    ✅       ✅       ✅       🟡       ✅       ✅      │
│   33/33    21/21     5/5      3/5      1/1      1/1    │
└─────────────────────────────────────────────────────────┘
```

**Data Sources:**
- Firestore: `phase2_completion`, `phase3_completion`, `processor_heartbeats`
- BigQuery: `processor_run_history`, `player_prop_predictions`, `prediction_accuracy`
- Cloud Monitoring: Service health, DLQ counts

**Health Score Calculation:**
```python
health_score = (
    phase_success_rate * 0.30 +      # 30%: Pipeline execution
    data_quality_score * 0.25 +      # 25%: Data completeness
    prediction_accuracy * 0.25 +     # 25%: Model performance
    service_uptime * 0.15 +          # 15%: Infrastructure
    cost_efficiency * 0.05           #  5%: Cost control
)
```

---

#### **Page 2: PIPELINE HEALTH**

**Purpose:** Real-time visibility into 6-phase data pipeline

**Key Visualizations:**

1. **Animated Phase Flow** (SVG with pulse animations)
   - Shows data flowing through phases
   - Color-coded: Green (complete), Yellow (in-progress), Red (failed)
   - Click any phase to drill down

2. **Phase Breakdown Table**
   ```
   Phase | Processors | Status | Completion | Avg Duration | Errors
   ------+------------+--------+------------+--------------+-------
   1     | 33 scrapers| ✅     | 33/33      | 12m 34s      | 0
   2     | 21 raw     | ✅     | 21/21      | 8m 11s       | 0
   3     | 5 analytics| ✅     | 5/5        | 1h 44m       | 0
   4     | 5 precomp  | 🟡     | 3/5        | 2h 18m       | 2
   5     | Predictions| ✅     | 1/1        | 47m          | 0
   6     | Publishing | ✅     | 1/1        | 18m          | 0
   ```

3. **Processor Heartbeats** (Real-time gauges)
   - Shows active processors with last heartbeat time
   - Alerts when heartbeat >5 minutes (stale)
   - Auto-recovery countdown for stalled processors

4. **Dependency Graph** (D3.js force layout)
   - Shows which processors depend on which data sources
   - Highlights missing dependencies in red
   - Click to see table freshness

5. **Recent Phase Transitions** (Timeline)
   - Shows orchestrator decisions (RUN/SKIP/WAIT)
   - Tracks phase completion times
   - Highlights bottlenecks

**Data Sources:**
- Firestore: `processor_heartbeats`, `phase2_completion`, `phase3_completion`
- BigQuery: `processor_run_history`, `phase_execution_log`
- BigQuery INFORMATION_SCHEMA: Table row counts and last update times

---

#### **Page 3: PREDICTION QUALITY** ⭐ ML Performance

**Purpose:** Track model accuracy, ROI, and business value

**Key Panels:**

1. **ROI Profitability Gauge** (Radial gauge)
   ```
   TODAY'S BETTING ROI: +8.2%

   Flat betting: +$470 (52 bets)
   High conf (90+): +$890 (24 bets)
   Win rate: 56.4%
   ```

2. **Confidence vs Edge Matrix** (2x2 heatmap)
   ```
   HIGH CONFIDENCE (90+)
   ┌─────────────────┬──────────────────┐
   │ "Confident      │ "Confident       │
   │  No Value"      │  & Value" ⭐     │
   │ 245 preds (12%) │ 243 preds (13%)  │
   │ 51.9% hit       │ 77% hit          │
   ├─────────────────┼──────────────────┤
   │ "Uncertain      │ "Uncertain       │
   │  No Value"      │  But Edge"       │
   │ 892 preds       │ 105 preds        │
   │ 38% hit         │ 52% hit          │
   └─────────────────┴──────────────────┘
          LOW EDGE         HIGH EDGE (3+)
   ```

3. **Calibration Curve** (Line chart)
   - X-axis: Predicted confidence (50%, 60%, 70%, 80%, 90%)
   - Y-axis: Actual accuracy
   - Diagonal line = perfect calibration
   - Show current models vs diagonal

4. **7-Day Accuracy Trend** (Time series)
   - Overall hit rate
   - By player tier (stars, starters, rotation, bench)
   - By prediction type (OVER vs UNDER)
   - Breakeven line at 52.4%

5. **Player Tier Performance Grid**
   ```
   Tier         | Hit Rate | MAE   | Volume | Best System
   -------------+----------+-------+--------+-------------
   Stars (30+)  | 58.2%    | 3.1pt | 124    | Ensemble_V1
   Starters     | 62.4%    | 2.9pt | 289    | CatBoost_V8
   Rotation     | 64.1%    | 2.8pt | 312    | Ensemble_V1
   Bench (<12)  | 45.8%    | 4.2pt | 176    | N/A (poor)
   ```

**Data Sources:**
- `nba_predictions.prediction_accuracy` (419K+ records since Nov 2021)
- `nba_predictions.player_prop_predictions`
- Views to create:
  - `v_prediction_quality_score`
  - `v_calibration_diagnostic`
  - `v_player_system_profitability`
  - `v_roi_summary`

**Key Insight from Research:**
- Confidence + Edge together = 77% hit rate (excellent)
- Confidence alone (90+) = 51.9% (loses money)
- Edge alone (3+) = 56.0% (barely profitable)
- **Strategic filtering is key to profitability**

---

#### **Page 4: DATA QUALITY**

**Purpose:** Proactive monitoring of data sources and feature health

**Key Sections:**

1. **Source Health Scorecard**
   ```
   Source              | Trust Score | Freshness | Coverage | Status
   --------------------+-------------+-----------+----------+--------
   NBA.com (NBAC)      | 99/100 ✅   | 2 min     | 100%     | EXCELLENT
   BigDataBall (BDB)   | 87/100 🟡   | 45 min    | 87%      | DEGRADED
   OddsAPI             | 92/100 ✅   | 5 min     | 96%      | GOOD
   BettingPros         | 85/100 🟡   | 1h 15m    | 89%      | ACCEPTABLE
   BDL (Disabled)      | 41/100 🔴   | N/A       | 0%       | DISABLED
   ESPN                | 78/100 🟡   | 2h 30m    | 97%      | DELAYED
   ```

2. **Shot Zone Quality Trend** (Session 53/54 monitoring)
   - Last 7 days completeness %
   - Paint/three/mid-range rate distributions
   - Anomaly counts (paint <25%, three >55%)
   - BDB availability correlation

3. **Feature Store Health**
   ```
   Feature Name       | Completeness | Quality | Freshness
   -------------------+--------------+---------+----------
   recent_ppg         | 100%         | ✅      | 2 min
   paint_rate         | 42%          | 🔴      | 2 min (MISSING)
   three_point_rate   | 92%          | ✅      | 2 min
   usage_rate         | 98%          | ✅      | 1 day
   ```

4. **Data Gap Tracker**
   - Active gaps with severity, age, impact
   - Auto-backfill queue status
   - Resolution time estimates

5. **BDL Readiness Status** (Session 41 monitoring)
   - 7-day quality trend (currently: 73% accuracy vs 95% threshold)
   - Major discrepancy % (needs <5% for 7 consecutive days)
   - Recommendation: Keep disabled or consider re-enabling

**Data Sources:**
- `nba_orchestration.shot_zone_quality_trend` (newly created Session 54)
- `nba_orchestration.bdl_quality_trend` (Session 41)
- `nba_orchestration.data_gaps`
- `nba_predictions.ml_feature_store_v2`
- BigQuery INFORMATION_SCHEMA for table freshness

---

#### **Page 5: SCRAPERS & PHASE 1**

**Purpose:** Migrate existing scraper dashboard, show Phase 1 health

**Sections:**
1. Gap counts by scraper (from existing dashboard)
2. Proxy health metrics
3. Circuit breaker states
4. Recent backfill activity
5. Scraper efficiency (success rate, retry %, cost per scrape)

**Migration:**
- Copy functionality from `/orchestration/cloud_functions/scraper_dashboard/`
- Apply white theme
- Integrate with unified navigation

---

#### **Page 6: ALERTS & INCIDENTS**

**Purpose:** Unified alert management and incident tracking

**Sections:**

1. **Active Alerts** (Severity-sorted)
   ```
   Sev    | Alert Type            | Time    | Status   | Action
   -------+-----------------------+---------+----------+--------
   🔴 CRIT| DLQ Messages (23)     | 2h ago  | ACTIVE   | [Replay]
   🟡 WARN| Model Calibration Low | 4h ago  | ACTIVE   | [Retrain]
   🟡 WARN| Shot Zones 40%        | 8h ago  | ACTIVE   | [Check BDB]
   🟢 INFO| Phase 2 Success       | 10m ago | RESOLVED | [Dismiss]
   ```

2. **Issue Tracker** (Like GitHub issues)
   - Open/In-progress/Resolved
   - Assigned owner
   - Root cause tags
   - Related alerts

3. **DLQ Monitor**
   - Message counts per DLQ topic
   - Oldest message age
   - One-click replay
   - Replay history

4. **Incident Timeline** (Last 7 days)
   - Shows what happened, when, and how it was resolved
   - Links to related commits, deployments, alerts

**Data Sources:**
- Cloud Logging alerts
- `nba_orchestration.circuit_breaker_state`
- Pub/Sub metrics (DLQ counts)
- Custom incident tracking table (to be created)

---

#### **Page 7: COST & EFFICIENCY**

**Purpose:** Business intelligence and optimization opportunities

**Key Dashboards:**

1. **Cost Per Prediction** (THE metric)
   ```
   Cost per prediction: $0.000045

   Breakdown:
   - BigQuery: $0.000028 (62%)
   - Cloud Run: $0.000012 (27%)
   - API costs: $0.000005 (11%)

   Target: $0.000030 (-33%)
   ```

2. **Resource Waste Identification**
   - Cloud Run over-provisioning (70% CPU unused)
   - BigQuery cache efficiency (45% vs 60-80% target)
   - Scraper retry waste (5-25% by scraper)
   - Slow phases (Phase 4: 45s vs 10s threshold)

3. **Optimization Opportunities** (Ranked by ROI)
   ```
   Priority | Opportunity              | Annual Savings | Effort | ROI
   ---------+--------------------------+----------------+--------+-----
   🔴 High  | Query result caching     | $3,360         | 20h    | 168x
   🔴 High  | Phase 4 latency fix      | $3,000         | 40h    | 75x
   🟡 Med   | Right-size containers    | $2,700         | 10h    | 270x
   🟡 Med   | Scraper retry optimization| $1,800        | 30h    | 60x
   ```

4. **Cost Trend Forecast** (30/60/90 days)
   - Linear regression on historical costs
   - Seasonal adjustments (playoffs, weather)
   - Scenario modeling

5. **Efficiency Gains Tracker**
   - Before/after metrics for each optimization
   - Cost attribution to code changes
   - Progress toward targets

**Data Sources:**
- `region-us.INFORMATION_SCHEMA.JOBS` (BigQuery costs)
- Cloud Monitoring (Cloud Run metrics)
- `nba_orchestration.scraper_cost_metrics`
- Tables to create:
  - `cost_optimization.cost_summary`
  - `cost_optimization.efficiency_metrics`
  - `cost_optimization.optimization_tracking`

---

#### **Page 8: SYSTEM HEALTH**

**Purpose:** Infrastructure monitoring (services, quotas, deployments)

**Sections:**

1. **Cloud Run Services**
   ```
   Service                  | Status | Revision    | Deployed
   -------------------------+--------+-------------+----------
   prediction-coordinator   | ✅     | 00142@sha.. | 2.1h ago
   prediction-worker        | ✅     | 00098@sha.. | 6.2h ago
   nba-phase3-analytics     | ✅     | 00217@sha.. | 12m ago
   nba-phase4-precompute    | ✅     | 00189@sha.. | 1.5h ago
   ```

2. **BigQuery Costs & Quota**
   - Query costs (last 24h): $6.42
   - Storage: 814 GB ($4.07/mo)
   - Quota usage: 287/1500 jobs (19%)

3. **Pub/Sub Topics & DLQs**
   - Message backlogs by topic
   - DLQ counts
   - Ack rates

4. **Deployment History**
   - Recent deployments with versions
   - Deployment drift detection
   - Rollback options

5. **Performance Metrics**
   - End-to-end latency (Phase 1→6)
   - P95/P99 latency percentiles
   - Throughput (predictions/hour)

---

## Technical Architecture

### Tech Stack Recommendation

```
┌─────────────────────────────────────────────────────────┐
│ FRONTEND                                                │
├─────────────────────────────────────────────────────────┤
│ • React + TypeScript                                    │
│ • Recharts (charts), D3.js (dependency graphs)         │
│ • Tailwind CSS (styling with white theme)             │
│ • WebSocket client (real-time updates)                │
│ • React Router (page navigation)                       │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ BACKEND                                                 │
├─────────────────────────────────────────────────────────┤
│ • FastAPI (Python 3.11)                                │
│ • WebSocket server (real-time push)                   │
│ • 15-minute cache layer (Redis or in-memory)          │
│ • Deployed on Cloud Run                                │
│ • Location: /services/unified_dashboard/              │
└─────────────────────────────────────────────────────────┘
                         ↓
┌──────────────────────────┬──────────────────────────────┐
│ FIRESTORE                │ BIGQUERY                     │
├──────────────────────────┼──────────────────────────────┤
│ • processor_heartbeats   │ • processor_run_history      │
│ • phase2_completion      │ • prediction_accuracy        │
│ • phase3_completion      │ • ml_feature_store_v2        │
│ • circuit_breaker_state  │ • shot_zone_quality_trend    │
│ (Real-time state)        │ (Historical analytics)       │
└──────────────────────────┴──────────────────────────────┘
```

### Directory Structure

```
/services/unified_dashboard/
├── backend/
│   ├── main.py                 # FastAPI app
│   ├── api/
│   │   ├── home.py             # Home page API
│   │   ├── pipeline.py         # Pipeline health API
│   │   ├── predictions.py      # Prediction quality API
│   │   ├── data_quality.py     # Data quality API
│   │   ├── scrapers.py         # Scraper health API
│   │   ├── alerts.py           # Alerts API
│   │   ├── costs.py            # Cost analytics API
│   │   └── system.py           # System health API
│   ├── models/
│   │   └── schemas.py          # Pydantic models
│   ├── services/
│   │   ├── firestore_client.py
│   │   ├── bigquery_client.py
│   │   └── cache_service.py
│   └── utils/
│       ├── health_calculator.py
│       └── metrics.py
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/
│   │   │   ├── Home.tsx
│   │   │   ├── Pipeline.tsx
│   │   │   ├── Predictions.tsx
│   │   │   ├── DataQuality.tsx
│   │   │   ├── Scrapers.tsx
│   │   │   ├── Alerts.tsx
│   │   │   ├── Costs.tsx
│   │   │   └── System.tsx
│   │   ├── components/
│   │   │   ├── HealthScore.tsx
│   │   │   ├── PhaseFlow.tsx
│   │   │   ├── AlertCard.tsx
│   │   │   ├── MetricCard.tsx
│   │   │   └── ...
│   │   └── hooks/
│   │       ├── useWebSocket.ts
│   │       └── useHealthScore.ts
│   ├── package.json
│   └── tailwind.config.js
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## Design System & UX

### Color Palette (White Theme)

Apply the scraper dashboard's clean white theme:

```css
/* Base Colors */
--bg-page: #f5f5f5;           /* Light gray page background */
--bg-card: #ffffff;           /* White card backgrounds */
--text-primary: #333333;      /* Dark text */
--text-secondary: #666666;    /* Secondary text */
--text-tertiary: #999999;     /* Muted text */
--border: #eeeeee;            /* Borders, dividers */

/* Status Colors (Keep consistent) */
--green-healthy: #28a745;     /* Success, healthy states */
--red-critical: #d32f2f;      /* Errors, critical states */
--yellow-warning: #ffc107;    /* Warnings, degraded states */
--orange-alert: #ff9800;      /* Medium severity */

/* Effects */
--shadow-card: 0 2px 4px rgba(0,0,0,0.1);
--border-radius: 8px;
```

### Typography

```css
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;

/* Heading sizes */
h1: 24px, bold, #333
h2: 18px, semi-bold, #333
h3: 16px, semi-bold, #666

/* Body text */
body: 14px, normal, #333
small: 12px, normal, #666
```

### Layout Principles

1. **Card-based design** - Everything in white cards with subtle shadows
2. **Responsive grid** - `repeat(auto-fit, minmax(400px, 1fr))`
3. **Consistent spacing** - 8px base unit (8, 16, 24, 32px)
4. **Status indicators** - Color + icon + text (never color alone)
5. **Progressive disclosure** - Summary first, drill-down on click

---

## Implementation Roadmap

### Phase 1: MVP - Home + Core Pages (Weeks 1-2)

**Goal:** Get something deployed and usable

**Build:**
1. Backend API scaffolding (FastAPI)
2. Home page (health score + alerts + pipeline flow)
3. Pipeline Health page (phase breakdown)
4. Prediction Quality page (accuracy trends)

**Deploy to:** Cloud Run at `/services/unified_dashboard/`

**Success Metrics:**
- Home page loads in <2 seconds
- Health score accurately reflects system state
- Alerts are actionable

---

### Phase 2: Data Quality + Scrapers (Weeks 3-4)

**Add:**
1. Data Quality page (source health, shot zones, feature store)
2. Scrapers page (migrate existing dashboard)
3. Shot zone quality visualization

**Integrate:**
- Firestore real-time updates
- BigQuery scheduled queries for trends

---

### Phase 3: Alerts + Cost + System (Weeks 5-6)

**Add:**
1. Alerts & Incidents page (DLQ monitor, issue tracker)
2. Cost & Efficiency page (cost per prediction, optimization opportunities)
3. System Health page (services, quotas, deployments)

**Implement:**
- One-click remediation actions
- Cost forecasting
- Deployment impact tracking

---

### Phase 4: Advanced Features (Weeks 7-8+)

**Innovative features:**
1. AI-powered pipeline trace (trace failed predictions backward)
2. Natural language queries ("Show predictions for star players last week")
3. Predictive health forecasting (predict quota issues 24h early)
4. Schema validation UI (side-by-side diffs)
5. Time-travel debugging (replay pipeline state)

---

## Key Research Findings

### User Workflows (From Agent Research)

**Top 5 jobs-to-be-done:**

1. **Morning Health Check** (10 min)
   - Are all services healthy?
   - Did overnight processing complete?
   - Are predictions ready for today?

2. **Incident Investigation** (30-90 min)
   - Which phase failed?
   - What was the error?
   - How much data was lost?

3. **Daily Predictions Release** (5-10 min)
   - How many predictions generated?
   - Coverage by game?
   - Shot zone data quality good?

4. **Performance Monitoring** (ongoing)
   - What's this week's hit rate?
   - Are we over/under-predicting?
   - Is there model drift?

5. **Deployment & Release** (15-30 min)
   - Which services deployed?
   - Did error rates spike?
   - Did accuracy change?

### Industry Best Practices

**Pattern #1: Information Hierarchy** (Pyramid)
```
Level 1: Blink status (GREEN/YELLOW/RED)
  ↓
Level 2: Phase breakdown (6 metrics)
  ↓
Level 3: Detailed metrics (40+ metrics)
  ↓
Level 4: Drill down (raw data)
```

**Pattern #2: Time-Series + Status**
- Show both current state AND trend
- Include reference lines (thresholds, benchmarks)
- Enable time range filtering

**Pattern #3: Anomaly + Context**
- What: Metric and threshold
- When: How long it's been red
- Why: Possible root causes
- Impact: What it affects
- Action: What to do

**Pattern #4: SLA-Based Color Coding**
```
Phase Completion SLA:
✅ GREEN:  >95% OR (>90% AND <2h old)
🟡 YELLOW: 80-95% OR >2h old
🔴 RED:    <80%
```

### Critical Insights

**From Prediction Analysis:**
- Confidence + Edge together = 77% hit rate
- Confidence alone (90+) = 51.9% (loses money)
- Edge alone (3+) = 56.0% (barely profitable)
- **Strategic filtering increases ROI by 188%**

**From Pipeline Analysis:**
- Phase 4 is bottleneck (45s avg vs 10s threshold)
- 5-phase orchestration with Firestore state tracking
- Heartbeat monitoring detects stalled processors (>5min = stale)
- Auto-recovery at 15 minutes

**From Data Quality:**
- Shot zone data: 87-90% completeness (excellent after Session 53 fix)
- BDL disabled (73% accuracy vs 95% threshold)
- BDB critical for shot zones (primary source)
- Feature store: 24% records missing shot zones (mostly old data)

**From Cost Analysis:**
- Cost per prediction: $0.000045 (potential to reduce to $0.000028)
- BigQuery cache hit rate: 45% (target: 60-80%)
- Phase 4 latency: Major cost driver (4.5x slower than expected)
- Cloud Run over-provisioned (70% CPU unused)

---

## Agent Investigation Results

### Agent 1: Modern Ops Dashboard Patterns

**Key Findings:**
- 5 main user workflows identified
- 3-layer information hierarchy recommended
- SLA-based color coding (not arbitrary red/yellow/green)
- Alert deduplication and grouping
- Self-healing indicators

**Document:** Agent output included in session logs

---

### Agent 2: Prediction-First Dashboard

**Key Deliverables:**
- Confidence vs Edge matrix (2x2 heatmap)
- Calibration curve design
- ROI attribution waterfall
- Player-system profitability analysis
- Prediction Quality Score (PQS) formula

**Key Insight:** Single metric that matters: `PQS = (Hit Rate - 52.4%) × 100 / 24.6`

---

### Agent 3: Real-Time Operations View

**Key Deliverables:**
- Animated phase flow design
- Dependency graph architecture
- One-click remediation actions
- Failure mode detection logic
- Traffic light system

**Key Insight:** Operators need to see pipeline status in 3 seconds

---

### Agent 4: Data Quality Intelligence

**Key Deliverables:**
- Trust score formula (0-100 per source)
- Predictive alerting (detect issues before impact)
- Cross-source reconciliation
- Gamification leaderboard
- Incident archaeology

**Key Insight:** Reactive → Proactive monitoring shifts prevent incidents

---

### Agent 5: Cost Optimization

**Key Deliverables:**
- Cost per prediction calculation
- Resource waste identification
- Optimization opportunity matrix
- Cost trend forecasting
- Efficiency ratio framework

**Key Insight:** Query result caching = $3,360/year savings (highest ROI)

---

### Agent 6: Innovative Features

**Top 10 Features:**
1. AI-powered pipeline trace (auto root cause)
2. Predictive health forecasting (ML on metrics)
3. Interactive schema validator
4. Multimodal anomaly detection
5. Collaborative annotations
6. Mobile-first alerts with one-tap remediation
7. Natural language queries
8. Deployment impact analyzer
9. Gamified system health
10. Time-travel debugging

---

## Files & References

### Created This Session

**Handoff Documents:**
- `docs/09-handoff/2026-01-31-SESSION-54-HANDOFF.md` - Shot zone monitoring implementation
- `docs/09-handoff/2026-01-31-SESSION-54-ML-FINDINGS.md` - ML model analysis (backfill decision)
- **THIS FILE** - Unified dashboard handoff

### Key Existing Files

**Current Dashboards:**
- `/orchestration/cloud_functions/pipeline_dashboard/main.py` - Dark theme, 717 lines
- `/orchestration/cloud_functions/scraper_dashboard/main.py` - White theme (user prefers)
- `/services/admin_dashboard/` - Comprehensive Flask app with 13 blueprints

**Monitoring Infrastructure:**
- `/orchestration/cloud_functions/data_quality_alerts/main.py` - 6 daily quality checks
- `/bin/monitoring/bdb_critical_monitor.py` - Shot zone data monitoring
- `/bin/monitoring/model_drift_detection.py` - Model degradation detection

**Data Tables:**
- `nba_predictions.prediction_accuracy` - 419K+ records (grading results)
- `nba_predictions.ml_feature_store_v2` - Feature store
- `nba_orchestration.shot_zone_quality_trend` - Created Session 54
- `nba_orchestration.bdl_quality_trend` - BDL readiness tracking
- `nba_reference.processor_run_history` - All processor executions

**Recent Sessions:**
- Session 41 (BDL quality issues) - Disabled BDL as backup source
- Session 53 (Shot zone corruption fix) - Fixed mixed data sources
- Session 54 (Shot zone monitoring) - Added dashboard + alerts
- **Session 56 (This session)** - Unified dashboard design

---

## Next Steps for New Session

### Immediate Actions (First Hour)

1. **Review this handoff document completely**
   - Understand the 8-page structure
   - Review agent research findings
   - Check technical architecture

2. **Explore existing dashboards**
   ```bash
   # View current dashboards
   ls -la orchestration/cloud_functions/pipeline_dashboard/
   ls -la orchestration/cloud_functions/scraper_dashboard/
   ls -la services/admin_dashboard/

   # Check what's deployed
   gcloud run services list --region=us-west2
   ```

3. **Understand data sources**
   ```bash
   # Check BigQuery tables
   bq ls nba_predictions
   bq ls nba_orchestration

   # Sample key tables
   bq head -n 5 nba_predictions.prediction_accuracy
   bq head -n 5 nba_orchestration.shot_zone_quality_trend
   ```

### Decision Points (Discuss with User)

**Question 1:** Which page to build first?
- **Option A:** Home page (health score + alerts)
- **Option B:** Prediction Quality (most business value)
- **Option C:** Pipeline Health (most operational value)

**Question 2:** Which tech stack?
- **Option A:** React + FastAPI (recommended, modern)
- **Option B:** Flask + Jinja templates (simpler, like existing)
- **Option C:** Google Data Studio (fastest, limited customization)

**Question 3:** MVP scope?
- **Option A:** Just Home page this week
- **Option B:** Home + 2 other pages this week
- **Option C:** All 8 pages in 2 weeks

### Recommended Approach (Week 1)

**Day 1-2: Setup**
```bash
# Create new service
mkdir -p services/unified_dashboard/{backend,frontend}

# Initialize FastAPI backend
cd services/unified_dashboard/backend
# Create main.py, requirements.txt, Dockerfile

# Initialize React frontend
cd ../frontend
npx create-react-app . --template typescript
npm install recharts d3 tailwindcss
```

**Day 3-4: Build Home Page**
- Backend API for health score calculation
- Frontend components (HealthScore, AlertCard, PhaseFlow)
- Firestore + BigQuery integration
- Deploy to Cloud Run

**Day 5: Testing & Refinement**
- Load testing
- UI polish
- Get user feedback
- Plan next pages

### Quick Start Commands

```bash
# Check current dashboards
curl "https://us-west2-nba-props-platform.cloudfunctions.net/pipeline-dashboard?format=json"

# Check shot zone quality
bq query --use_legacy_sql=false "
  SELECT * FROM nba_orchestration.shot_zone_quality_trend
  WHERE game_date >= CURRENT_DATE() - 7
  ORDER BY game_date DESC"

# Check prediction accuracy
bq query --use_legacy_sql=false "
  SELECT game_date,
    COUNTIF(prediction_correct) * 100.0 / COUNT(*) as hit_rate
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= CURRENT_DATE() - 7
  GROUP BY game_date
  ORDER BY game_date DESC"

# View service health
gcloud run services describe prediction-worker --region=us-west2
```

### Questions to Ask User

1. **What's the #1 pain point** you want the dashboard to solve first?
2. **Who are the primary users** (ops team, ML team, business, all)?
3. **Mobile access important** or desktop-only for now?
4. **Existing admin dashboard** at `/services/admin_dashboard/` - keep, replace, or merge?
5. **Timeline** - quick MVP (1 week) or comprehensive (4 weeks)?

---

## Success Criteria

The unified dashboard will be successful when:

✅ **Operators can assess system health in 3 seconds** (blink test)
✅ **Incident investigation time drops from 30+ min to <5 min**
✅ **All monitoring consolidated** (no need for 40+ manual queries)
✅ **Predictions tracked** with ROI, accuracy, calibration
✅ **Data quality monitored proactively** (predict issues before impact)
✅ **Costs tracked** with optimization opportunities ranked
✅ **One-click remediation** for common issues (DLQ replay, backfills)
✅ **Mobile-friendly** for on-call engineers

---

## Appendix: Agent Task IDs

For reference, here are the agent IDs if you need to review their full output:

1. **Modern Ops Dashboard Patterns:** `a418b44`
2. **Prediction-First Dashboard:** `ad17120`
3. **Real-Time Operations View:** `a8f7b7b`
4. **Data Quality Intelligence:** `a7f78ab`
5. **Cost Optimization:** `a125e6e`
6. **Innovative Features:** `a595132`

To resume any agent investigation:
```python
# In next session, if needed
Task(subagent_type="Explore", resume="a418b44", prompt="Continue investigation...")
```

---

## Final Notes

**This session accomplished:**
- ✅ Comprehensive research (6 parallel agent investigations)
- ✅ Complete dashboard design (8 pages specified)
- ✅ Technical architecture defined
- ✅ Implementation roadmap created
- ✅ Design system documented

**Next session should:**
- 🎯 Decide on MVP scope with user
- 🎯 Begin implementation
- 🎯 Deploy first working version

**Key principle:** Start simple, iterate fast, get feedback early.

---

**Handoff Status:** ✅ Complete
**Ready for:** Implementation
**Estimated effort:** 4-8 weeks for full dashboard
**Quick win available:** Home page in 1 week

---

*Created: 2026-01-31*
*Session: 56*
*For: Next session implementation*
*Contact: Review this doc + ask clarifying questions before starting*
