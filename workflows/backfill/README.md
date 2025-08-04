# Backfill Workflows

**Historical data collection workflows for building the foundation dataset needed for NBA prop betting analysis and predictive modeling.**

## Current Workflows

### Foundation Data Collection
- **`collect-nba-historical-schedules.yaml`** ⭐ **FOUNDATION**
  - Collects NBA.com schedules for 4 seasons: 2021-22, 2022-23, 2023-24, 2024-25
  - Creates master calendar that drives all other backfill processes
  - **Output**: `gs://nba-scraped-data/schedules/{season}-schedule.json`
  - **Execution**: One-time manual run (~5 minutes)

## Planned Workflows

### Main Historical Data Collection
- **`main-historical-backfill.yaml`** 🔄 **COMING NEXT**
  - 5-scraper strategy: Events → Props → Box Scores → Cross-validation
  - Schedule-driven processing (only dates with games)
  - Processes ~4,920 games across 4 seasons
  - **Dependencies**: Requires schedule collection to complete first

### Data Quality & Recovery  
- **`validate-historical-data.yaml`** 🔄 **PLANNED**
  - Cross-validation between data sources
  - Data quality checks and completeness verification
  - Gap detection and reporting

- **`backfill-recovery.yaml`** 🔄 **PLANNED**
  - Recovery workflow for failed backfill jobs
  - Selective retry of missing dates/games
  - Resume capability from checkpoints

## Business Purpose

**Goal**: Build comprehensive historical dataset for prop betting predictions

**Strategy**: Schedule-driven backfill approach
- Use NBA.com schedules as master calendar
- Only process dates with actual games (no wasted API calls)
- Cross-reference multiple data sources for quality
- Include both regular season and playoff games

**Data Sources**:
- **Ball Don't Lie API**: Player statistics and box scores
- **Odds API**: Historical prop betting lines and events  
- **NBA.com**: Official schedules, rosters, and injury reports
- **Big Data Ball**: Enhanced play-by-play (already collected - 3,962 files)

## Execution Strategy

### Phase 1: Foundation (Current)
1. ✅ **Big Data Ball files organized** (3,962 games, 2021-2024)
2. 🏃 **Schedule collection** (`collect-nba-historical-schedules.yaml`)
3. 🔄 **Main backfill workflow** (next step)

### Phase 2: Historical Data Collection  
- Date-by-date processing using collected schedules
- API rate limiting respect (BDL: 600/min, Odds API: 500/month)
- Comprehensive error handling and resume capability
- Cross-validation and quality checks

### Phase 3: Validation & Enhancement
- Data quality analysis across all sources
- Gap analysis and filling
- Performance optimization based on execution learnings

## Deployment & Execution

```bash
# Deploy backfill workflows
./bin/deployment/deploy_workflows.sh workflows/backfill/

# Execute schedule collection (foundation)
gcloud workflows run collect-nba-historical-schedules --location=us-west2

# Verify schedule collection results
gcloud storage ls gs://nba-scraped-data/schedules/

# Execute main backfill (after schedules complete)
gcloud workflows run main-historical-backfill --location=us-west2
```

## Data Output Structure

```
gs://nba-scraped-data/
├── schedules/                    # Foundation schedules (this workflow)
│   ├── 2021-22-schedule.json
│   ├── 2022-23-schedule.json  
│   ├── 2023-24-schedule.json
│   ├── 2024-25-schedule.json
│   └── collection-summary.json
├── odds-api/                     # Historical betting data (main backfill)
│   ├── events-history/
│   └── player-props-history/
├── ball-dont-lie/               # Historical player stats (main backfill)
│   └── box-scores-history/
└── big-data-ball/               # ✅ COMPLETE (3,962 files)
    ├── 2021-22/
    ├── 2022-23/
    └── 2023-24/
```

## Success Metrics

**Technical**:
- Data completeness >95% for scheduled games
- API success rate >98% per data source  
- Cross-validation accuracy >95% between sources

**Business**:
- Complete prop betting context for 4,920+ games
- Historical performance database for predictive modeling
- Foundation for sophisticated prop betting analysis

## Notes

- **Manual Execution**: These are one-time or on-demand workflows, not scheduled
- **API Usage**: Carefully manages rate limits across multiple APIs
- **Resume Capability**: All workflows support checkpoint-based recovery
- **Monitoring**: Comprehensive logging and progress tracking
