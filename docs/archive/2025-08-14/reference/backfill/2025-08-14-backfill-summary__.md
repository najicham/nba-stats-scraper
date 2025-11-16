# NBA Props Platform - Historical Backfill Summary

**Document Version:** 1.0  
**Date:** August 13, 2025  
**Status:** Core backfill complete, supplemental data ongoing

## Executive Summary

Successfully collected 4 seasons (2021-2025) of comprehensive NBA data across multiple sources to power prop betting analytics. Core dataset includes game schedules, player performance data, prop betting odds, and supporting roster information.

**Total Data Collected:** 15,000+ files across 4 seasons  
**Coverage Period:** 2021-22 through 2024-25 seasons  
**Data Quality:** 99%+ validation success rate  
**Storage:** ~15GB organized in Google Cloud Storage

## Data Sources & Collection Results

### 🏗️ Foundation Backfill (Google Cloud Workflows)

### ✅ NBA.com Schedule Collection - COMPLETE
**Purpose:** Foundation game inventory enabling all subsequent backfills  
**Implementation:** Google Cloud Workflow (not Cloud Run job)  
**Workflow File:** `workflows/backfill/collect-nba-historical-schedules.yaml`

**Architecture:**
- Uses existing scraper service (`nbac_schedule_api`) 
- One workflow call per season
- Highly efficient: 4 files total for 4 seasons

**Results:**
- **Coverage:** 4 complete seasons (2021-2025)
- **Total Games:** 5,583 games collected  
- **File Size:** ~3.3MB per season
- **Storage:** `gs://nba-scraped-data/nba-com/schedule/{season}/{timestamp}.json`
- **Metadata:** `gs://nba-scraped-data/nba-com/schedule-metadata/{season}/{timestamp}.json`

**Sample Season Stats (2021-22):**
- Total Games: 1,393 (Regular: 1,230, Playoffs: 93, All-Star: 4, Preseason: 66)
- Backfill Target: 1,323 games (excludes All-Star games and invalid teams)
- Completion: 100% of historical data

**Critical Dependency:** All other backfill jobs read these schedule files to extract game dates, avoiding inefficient date-range processing.

**Future Enhancements:** 
- Consider adding validation script to match other backfill jobs' quality assurance patterns
- Add jq-based data inspection script for quick validation of specific dates, game counts, and team codes

### 📊 Historical Data Backfills (Cloud Run Jobs)

### ✅ NBA.com Gamebooks - COMPLETE
**Purpose:** Player box scores, game context, injury status  
**Coverage:** 4 complete seasons (2021-2025)  
**Files Collected:** 7,128+ JSON files  
**Success Rate:** 99.6%

**Data Includes:**
- Complete player statistics per game
- Active/inactive player rosters  
- DNP reasons and injury status (last names only)
- Game officials, arena, final scores
- Team performance metrics

**Technical Implementation:**
- Cloud Run job: `nba-gamebook-backfill`
- Storage: `gs://nba-scraped-data/nba-com/gamebooks-data/{date}/{game-code}/`
- Runtime: 14 hours total
- Validation: Two-layer system with 99.6% success

### ✅ Odds API - PARTIAL COMPLETE
**Purpose:** Historical prop betting odds and lines  
**Coverage:** Events (2021-2025), Props (May 2023-2025)  
**Success Rate:** 95%+

**Events Collection:**
- 4 complete seasons of NBA games
- Event IDs for prop data lookup
- Storage: `gs://nba-scraped-data/odds-api/events-history/{season}/`

**Props Collection:**
- **2022-23 Season:** May 2023 onwards only (partial)
- **2023-24 Season:** Complete season
- **2024-25 Season:** Complete season  
- Player points props with closing odds
- Storage: `gs://nba-scraped-data/odds-api/props-history/{season}/`

**Rate Limiting:** 30 calls/second, 1.5s delays between calls

### ✅ BettingPros - COMPLETE
**Purpose:** Fill gaps in historical prop data (2021-2023)  
**Coverage:** 4 complete seasons (2021-2025)  
**Files Collected:** 800+ files

**Data Includes:**
- Player points props with multiple sportsbook odds
- Historical betting lines and movement
- Coverage for periods missing from Odds API

**Technical Implementation:**
- Cloud Run job: `nba-bp-backfill`
- Storage: `gs://nba-scraped-data/bettingpros/`
- Runtime: 4-6 hours
- Rate limiting: 3 seconds between calls

### ✅ Basketball Reference Rosters - COMPLETE
**Purpose:** Supporting data for player name resolution  
**Coverage:** 4 complete seasons (2021-2025)  
**Files Collected:** 120 roster files (30 teams × 4 seasons)

**Business Value:**
- Maps last names from gamebooks to full player names
- Example: "Morant" (from injury report) → "Ja Morant"
- Critical for accurate player identification in analytics

**Storage:** `gs://nba-analytics-raw-data/raw/basketball_reference/season_rosters/`

### ✅ NBA.com Schedules - COMPLETE
**Purpose:** Game inventory and scheduling foundation  
**Coverage:** 4 complete seasons  
**Files Collected:** 5,583 games

**Usage:** Foundation data for all other collection workflows

### ✅ Big Data Ball Enhanced Play-by-Play - PARTIAL COMPLETE
**Purpose:** Advanced play-by-play data with shot locations and defensive matchups  
**Coverage:** 3 seasons complete (2021-2023), 2024-25 pending  
**Source:** Purchased season data downloads + Google Drive access

**Data Includes:**
- Enhanced PBP with 40+ fields per event
- Shot locations and defensive matchups  
- ~500-800 events per game
- Advanced analytics-ready format

**Status:** 
- 2021-22, 2022-23, 2023-24: ✅ Complete (purchased and organized)
- 2024-25: 📋 Pending Google Drive collection via Cloud Run job

## Storage Architecture

```
gs://nba-scraped-data/
├── nba-com/
│   ├── schedule/2021-22/ → 2024-25/          # 5,583 games
│   └── gamebooks-data/2021-22/ → 2024-25/    # 7,128+ files
├── basketball-reference/
│   └── season-rosters/2021-22/ → 2024-25/    # 120 files
├── odds-api/
│   ├── events-history/2021-22/ → 2024-25/    # 4 seasons
│   └── props-history/2023-24/ → 2024-25/     # May 2023+
├── bettingpros/
│   ├── events/2021-22/ → 2024-25/            # 4 seasons
│   └── player-props/points/2021-22/ → 2024-25/
└── big-data-ball/
    └── enhanced-pbp/
        ├── 2021-22/ → 2023-24/               # 3 seasons complete (purchased)
        └── 2024-25/                          # Pending Google Drive collection

Future additions:
├── nba-com/injury-reports/                   # Planned: NBA.com injury PDFs
└── ball-dont-lie/boxscores/                  # Planned: BDL comparison data
```

## Technical Implementation

### File Organization Structure

**Backfill Infrastructure (source_datatype pattern):**
```
backfill/
├── nbac_gamebook/           # NBA.com gamebook data
│   ├── Dockerfile.nbac_gamebook_backfill
│   ├── nbac_gamebook_backfill.py
│   └── deploy_nbac_gamebook_backfill.sh
├── nbac_injury/             # NBA.com injury reports (ready for implementation)
├── odds_api_props/          # Odds API player props
│   ├── Dockerfile.odds_api_props_backfill
│   ├── odds_api_props_backfill.py
│   └── deploy_odds_api_props_backfill.sh
├── bp_props/                # BettingPros player props
│   ├── Dockerfile.bp_props_backfill
│   ├── bp_props_backfill.py
│   └── deploy_bp_props_backfill.sh
├── br_rosters/              # Basketball Reference rosters
│   ├── br_rosters_backfill_job.sh
│   └── deploy_br_rosters_backfill.sh
├── bdb_play_by_play/        # Big Data Ball enhanced PBP
│   └── organize_bdb_files.sh
└── bdl_boxscore/            # Ball Don't Lie box scores (future)
    ├── bdl_boxscore_backfill.py
    └── deploy_bdl_boxscore_backfill.sh
```

**Monitoring & Validation Tools:**
```
bin/
├── backfill/                # Backfill job monitoring
│   ├── nbac_gamebook_monitor.sh
│   ├── odds_api_props_monitor.sh
│   ├── bp_props_monitor.sh
│   ├── br_rosters_monitor.sh
│   ├── bdb_play_by_play_monitor.sh
│   └── bdl_boxscore_monitor.sh
└── validation/              # Data quality validation
    ├── validate_nbac_gamebook.sh
    ├── validate_odds_api_props.sh
    ├── validate_bp_props.sh
    ├── validate_br_rosters.sh
    ├── validate_bdb_play_by_play.sh
    └── validate_bdl_boxscore.sh
```

**Foundation Workflow:**
```
workflows/backfill/
└── collect-nba-historical-schedules.yaml  # Google Cloud Workflow
```

### Cloud Run Jobs Deployed
- `nba-gamebook-backfill` - NBA.com game data
- `nba-odds-api-season-backfill` - Odds API collection  
- `nba-bp-backfill` - BettingPros historical data
- `nba-schedule-backfill` - Game schedules (workflow-based)

### Key Features
- **Resume Logic:** All jobs skip existing data for safe restarts
- **Rate Limiting:** Respectful API usage patterns
- **Validation:** Multi-layer data quality checks
- **Monitoring:** Real-time progress tracking
- **Error Handling:** Comprehensive retry and fallback logic

### Organizational Benefits
- **Consistent Patterns:** Every backfill follows `source_datatype` naming convention
- **Complete Coverage:** Each backfill has infrastructure, monitoring, and validation
- **Easy Scaling:** Add new backfills by copying directory structure
- **Clear Separation:** Infrastructure (backfill/), monitoring (bin/backfill/), validation (bin/validation/)
- **Production Ready:** Standardized deployment and monitoring across all jobs

### API Rate Limits Applied
- **Odds API:** 30 calls/second (1.5s delays)
- **BettingPros:** 3 seconds between calls
- **NBA.com:** Conservative usage patterns
- **Basketball Reference:** 3.5 second delays (20 req/min)

## Data Quality & Coverage

### Coverage Completeness
| Data Source | 2021-22 | 2022-23 | 2023-24 | 2024-25 |
|-------------|---------|---------|---------|---------|
| NBA Gamebooks | ✅ 100% | ✅ 100% | ✅ 100% | ✅ 100% |
| NBA Schedules | ✅ 100% | ✅ 100% | ✅ 100% | ✅ 100% |
| Odds API Events | ✅ 100% | ✅ 100% | ✅ 100% | ✅ 100% |
| Odds API Props | ❌ 0% | ⚠️ Partial | ✅ 100% | ✅ 100% |
| BettingPros Props | ✅ 100% | ✅ 100% | ✅ 100% | ✅ 100% |
| BR Rosters | ✅ 100% | ✅ 100% | ✅ 100% | ✅ 100% |
| Big Data Ball PBP | ✅ 100% | ✅ 100% | ✅ 100% | 📋 Pending |

### Validation Results
- **NBA Gamebooks:** 99.6% success rate (7,128+ files validated)
- **Odds API:** 95%+ collection success
- **BettingPros:** 90%+ success (some pagination limitations)
- **Basketball Reference:** 100% success rate

## Business Value Delivered

### Immediate Analytics Capabilities
- **Player Performance:** 4 seasons of complete box scores
- **Prop Analysis:** Historical betting lines vs actual performance
- **Player Identification:** Full name resolution system ready
- **Market Analysis:** Multiple sportsbook comparison data

### Model Training Foundation
- **Historical Context:** 4+ seasons for robust pattern analysis
- **Data Quality:** Production-ready with comprehensive validation
- **Complete Timeline:** Game performance + betting market data aligned

## Future Backfill Plans

### 📋 Next Priority
- **Big Data Ball 2024-25:** Complete enhanced play-by-play dataset via Google Drive Cloud Run job
- **NBA.com Injury Reports:** Historical PDF collection for player availability context

### 🔍 Under Evaluation  
- **Ball Don't Lie Box Scores:** Small dataset for comparison to gamebook data (low priority)

### ❌ Not Planned
- **NBA.com Player Box Scores:** Redundant with existing gamebook data

## Key Lessons Learned

### Technical
- **Schedule-based approach:** More reliable than date ranges for NBA data
- **Resume logic essential:** Large backfills need restart capability  
- **Multi-source strategy:** BettingPros fills Odds API gaps effectively
- **Validation critical:** Catches special games, data quality issues
- **Consistent organization:** `source_datatype` naming enables easy scaling

### Business
- **Odds API limitations:** Props data only available from May 2023
- **Name resolution needed:** Basketball Reference rosters solve gamebook limitation
- **Quality over quantity:** 99%+ success rate more valuable than 100% coverage
- **Foundation first:** Schedule collection enables efficient processing for all others

### Organizational
- **Pattern consistency:** Every backfill follows same 3-file structure
- **Complete coverage:** Infrastructure + monitoring + validation for each source
- **Clear separation:** Different directories for different purposes
- **Production ready:** Standardized approach scales across all data sources

## Operational Status

### Production Ready
- All core scrapers deployed and validated
- Monitoring and alerting systems active
- Data processing pipelines ready for analytics integration
- Quality assurance systems operational

### Next Steps
1. **Big Data Ball 2024-25:** Cloud Run job for Google Drive collection
2. **Analytics Integration:** Connect historical data to current season workflows
3. **Model Development:** Train prop prediction models on complete dataset  
4. **Real-time Integration:** Combine historical patterns with live data
5. **Injury Reports:** Historical PDF collection for availability context

---

**Document Owner:** Data Engineering Team  
**Total Implementation Time:** 6 weeks  
**Data Foundation Status:** Complete and production-ready  
**Next Phase:** Analytics integration and model training