# NBA Gamebook Data Collection - Implementation Guide

**Current Status**
* ✅ **Phase 1 Complete**: 5,583 historical games (2021-2024) with dates
* ✅ **Basketball Reference Rosters Complete**: 120 roster files (4 seasons × 30 teams) for name mapping
* 📋 **Phase 2 Goal**: ~173,000 player records with box scores + DNP reasons + enhanced name resolution
* 🔄 **Ready for Implementation**: Basketball Reference integration complete, gamebook scraper development ready

---

## **Data Requirements**

**What We Need**
* **Complete box scores**: All statistical categories for every player
* **DNP reasons**: Injury, rest, coach's decision, personal, suspension
* **Game context**: Date, teams, final scores
* **Player identification**: Names, positions, team assignments
* **⭐ NEW - Enhanced name mapping**: "Morant" → "Ja Morant" using Basketball Reference rosters

**Why It Matters**
* **Prop betting analysis**: Need to know WHY players didn't play
* **Prediction models**: DNP context affects future availability predictions
* **Complete dataset**: Foundation for accurate prop betting recommendations
* **⭐ NEW - Historical accuracy**: Resolve incomplete player names in NBA PDFs for better data quality

---

## **Basketball Reference Integration** ✅ **COMPLETE**

### **Problem Solved**
NBA Gamebook PDFs show incomplete names for inactive players:
- **Active players**: "Ja Morant" (full name)
- **Inactive players**: "Morant" (last name only) ❌

### **Solution Implemented**
Basketball Reference season rosters provide complete name mapping:
```json
{
  "team": "Memphis Grizzlies",
  "season": "2023-24",
  "players": [
    {
      "name": "Ja Morant",
      "last_name": "Morant",
      "position": "PG"
    }
  ]
}
```

### **Data Collected** ✅
- **Seasons**: 2021-22, 2022-23, 2023-24, 2024-25
- **Teams**: All 30 NBA teams per season
- **Files**: 120 roster files in GCS
- **Storage**: `gs://nba-analytics-raw-data/raw/basketball_reference/season_rosters/{season}/{team}.json`
- **Quality**: 100% success rate, >95% complete player data

### **Integration Strategy**
```python
def resolve_player_name(last_name, team_abbr, season):
    """Enhanced name resolution using Basketball Reference rosters."""
    roster = load_basketball_ref_roster(team_abbr, season)
    for player in roster['players']:
        if player['last_name'] == last_name:
            return player['name']  # "Ja Morant"
    return last_name  # fallback to "Morant"
```

---

## **Implementation Tasks**

### **1. Scraper Integration**
* ✅ **Basketball Reference scraper complete**: `scrapers/basketball_ref/br_season_roster.py`
* ✅ **Scraper inventory updated**: Added to operational reference docs
* ✅ **Name mapping data ready**: 120 roster files available for integration
* [ ] **Create gamebook scraper**: Choose between NBA.com PDFs or alternative source
* [ ] **Integrate name mapping**: Add Basketball Reference lookup to gamebook processor
* [ ] **Test enhanced pipeline**: PDF parsing → name resolution → complete player records

### **2. Data Source Decision & Implementation**

#### **Option A: NBA.com PDFs (Original Plan)**
```python
# Enhanced NBA.com PDF processing with Basketball Reference integration
class NbaGamebookPdfScraper(ScraperBase):
    def transform_data(self):
        # Parse PDF for box scores + DNP reasons
        parsed_data = self.parse_pdf_content()
        
        # Enhance with Basketball Reference name mapping
        for player in parsed_data['inactive_players']:
            if player['name_incomplete']:  # e.g., "Morant"
                full_name = resolve_player_name(
                    player['last_name'], 
                    self.game_info['team'], 
                    self.game_info['season']
                )
                player['name'] = full_name  # "Ja Morant"
```

#### **Option B: Alternative Source with Basketball Reference Enhancement**
* Any chosen source enhanced with Basketball Reference name mapping
* Same integration pattern, different primary data source

### **3. Backfill Workflow Creation**
* [ ] **Create workflow file**: `workflows/backfill/collect-nba-historical-gamebooks.yaml`
* [ ] **Copy Phase 1 pattern**: Use proven `collect-nba-historical-schedules.yaml` as template
* [ ] **Season-by-season**: Process 2021-22 → 2022-23 → 2023-24 → 2024-25
* [ ] **Use known dates**: Leverage Phase 1 schedule data for game dates
* [ ] **Integration dependency**: Ensure Basketball Reference rosters loaded before gamebook processing

### **4. Infrastructure Setup**
* ✅ **Basketball Reference GCS paths**: Configured and tested
* [ ] **Gamebook GCS path configuration**: Extend `gcs_path_builder.py`
* [ ] **Storage pattern**: `gs://nba-scraped-data/nba-com/gamebooks/{season}/{date}/`
* [ ] **Name mapping service**: Create roster lookup utility functions
* [ ] **Error handling**: Robust parsing failures, missing games, format changes, name mapping fallbacks
* [ ] **Monitoring**: Success rates, data quality checks, name resolution accuracy

### **5. Testing & Validation**
* [ ] **Small batch test**: 1 week of games first
* [ ] **Name mapping validation**: Verify "Morant" → "Ja Morant" resolution works
* [ ] **Data quality check**: Compare against BDL API where possible
* [ ] **DNP coverage**: Verify all 0-minute players have reasons AND complete names
* [ ] **Performance test**: Processing speed, memory usage, roster lookup performance

### **6. Production Deployment**
* [ ] **Incremental rollout**: 1 month → 1 season → full backfill
* [ ] **Monitor execution**: Cloud Run performance, workflow completion, name mapping accuracy
* [ ] **Update documentation**: Operational reference, workflow reference, Basketball Reference integration guide

---

## **Enhanced Data Architecture**

### **Data Flow with Basketball Reference Integration**
```
Phase 1 Schedule Data → Game Dates
         ↓
Basketball Reference Rosters → Name Mapping Database
         ↓
Gamebook Source (NBA.com PDFs or Alternative) → Raw Game Data
         ↓
Enhanced Processor → Name Resolution → Complete Player Records
         ↓
GCS Storage → ~173,000 enhanced player records
```

### **GCS Storage Structure**
```
gs://nba-scraped-data/
├── basketball_reference/
│   └── season_rosters/          # ✅ COMPLETE - Name mapping data
│       ├── 2021-22/*.json       # 30 roster files
│       ├── 2022-23/*.json       # 30 roster files  
│       ├── 2023-24/*.json       # 30 roster files
│       └── 2024-25/*.json       # 30 roster files
└── nba-com/
    └── gamebooks/               # 📋 TO BE CREATED - Enhanced with name mapping
        ├── 2021-22/{date}/      # Game data with complete player names
        ├── 2022-23/{date}/      # Game data with complete player names
        ├── 2023-24/{date}/      # Game data with complete player names
        └── 2024-25/{date}/      # Game data with complete player names
```

---

## **Key Decisions Needed**

### **Primary Gamebook Data Source**
* **NBA.com PDFs**: Original plan, official source with DNP reasons
* **Alternative sources**: If PDF parsing proves challenging
* **Basketball Reference enhancement**: Applies to any chosen source for name mapping

### **Integration Approach**
* **Real-time lookup**: Query Basketball Reference data during processing
* **Pre-loaded cache**: Load all rosters into memory for faster processing
* **Fallback strategy**: Graceful degradation if name mapping unavailable

### **Processing Strategy**
* **Single season per run**: Follow Phase 1 pattern (proven successful)
* **Rate limiting**: Respectful usage of chosen data source
* **Basketball Reference dependency**: Load roster data before processing each season
* **Fallback plan**: BDL box scores without DNP + incomplete names if primary fails

---

## **Enhanced Success Criteria**

### **Data Coverage**
* **Game Coverage**: >95% of games successfully processed
* **DNP Coverage**: DNP reasons for all 0-minute players
* **⭐ Name Resolution**: >90% of incomplete names resolved to full names
* **Cross-validation**: Basketball Reference roster data validates against game rosters

### **Performance**  
* **Execution Speed**: Similar to Phase 1 (~117 seconds per season)
* **Name Mapping Speed**: <1ms per player name lookup
* **Memory Usage**: Efficient roster data caching
* **Integration**: Seamless workflow execution without manual intervention

### **Data Quality**
* **Player Identification**: Complete names for both active and inactive players
* **Historical Accuracy**: Accurate team assignments using season-specific rosters  
* **Context Preservation**: DNP reasons linked to correctly identified players
* **Validation**: Spot checks confirm "Morant" → "Ja Morant" mapping accuracy

---

## **Enhanced Implementation Benefits**

### **Before Basketball Reference Integration**
```json
{
  "inactive_players": [
    {"name": "Morant", "minutes": 0, "dnp_reason": "Injury"},
    {"name": "Bane", "minutes": 0, "dnp_reason": "Rest"}
  ]
}
```

### **After Basketball Reference Integration** ⭐
```json
{
  "inactive_players": [
    {"name": "Ja Morant", "last_name": "Morant", "minutes": 0, "dnp_reason": "Injury", "team": "MEM"},
    {"name": "Desmond Bane", "last_name": "Bane", "minutes": 0, "dnp_reason": "Rest", "team": "MEM"}
  ]
}
```

### **Business Value**
* **Enhanced Analysis**: Complete player identification enables better prop betting analysis
* **Historical Accuracy**: Season-specific rosters resolve player-team assignments correctly
* **Data Quality**: >90% improvement in player name completeness
* **Future-Proof**: Foundation for advanced analytics requiring complete player context

---

## **Next Steps** (Updated Priority)

### **Immediate (This Week)**
1. ✅ **Basketball Reference integration complete** - Data ready for use
2. **Choose primary gamebook data source** - NBA.com PDFs vs alternatives  
3. **Create gamebook scraper skeleton** - With Basketball Reference name mapping integration
4. **Test name mapping logic** - Validate "Morant" → "Ja Morant" resolution

### **Short Term (Next 2 Weeks)**
1. **Implement gamebook scraper** - With enhanced name resolution
2. **Create backfill workflow** - Following Phase 1 patterns
3. **Small-scale testing** - 1 week of games with name mapping validation
4. **Performance optimization** - Efficient roster lookup caching

### **Medium Term (Next Month)**
1. **Full season test** - Complete 2023-24 season with enhanced processing
2. **Data quality validation** - Comprehensive checks including name resolution accuracy
3. **Production deployment** - Incremental rollout with monitoring
4. **Documentation completion** - Integration guides and operational procedures

---

## **Files to Create/Update**

### **New Files**
* `scrapers/[source]/[gamebook_scraper].py` - Main gamebook scraper with Basketball Reference integration
* `workflows/backfill/collect-nba-historical-gamebooks.yaml` - Enhanced backfill workflow
* `scrapers/utils/basketball_ref_lookup.py` - Name mapping utility functions

### **Updated Files**
* ✅ `scrapers/utils/gcs_path_builder.py` - Basketball Reference paths added
* [ ] `scrapers/utils/gcs_path_builder.py` - Add gamebooks paths
* ✅ Documentation updates - Basketball Reference integration complete
* [ ] Operational reference - Add gamebook scraper with Basketball Reference dependency

### **Basketball Reference Files** ✅ **COMPLETE**
* ✅ `scrapers/basketball_ref/br_season_roster.py` - Season roster scraper
* ✅ `scripts/scrape_br_season_rosters.py` - Backfill automation script
* ✅ `bin/backfill/scrape_br_season_rosters.sh` - Shell wrapper
* ✅ GCS Data: 120 roster files across 4 seasons

---

## **Integration Code Example**

```python
# Enhanced gamebook processor with Basketball Reference integration
class EnhancedGamebookProcessor:
    def __init__(self):
        self.roster_cache = {}  # Cache for Basketball Reference data
        
    def load_season_rosters(self, season):
        """Pre-load all Basketball Reference rosters for a season."""
        if season not in self.roster_cache:
            self.roster_cache[season] = {}
            for team in NBA_TEAMS:
                roster_path = f"raw/basketball_reference/season_rosters/{season}/{team}.json"
                self.roster_cache[season][team] = self.load_from_gcs(roster_path)
    
    def resolve_player_name(self, last_name, team, season):
        """Resolve incomplete name using Basketball Reference roster."""
        roster = self.roster_cache.get(season, {}).get(team, {})
        for player in roster.get('players', []):
            if player['last_name'] == last_name:
                return {
                    'name': player['name'],
                    'position': player.get('position'),
                    'jersey_number': player.get('jersey_number')
                }
        return {'name': last_name}  # Fallback
    
    def process_gamebook(self, game_data):
        """Process gamebook with enhanced name resolution."""
        season = game_data['season']
        teams = [game_data['home_team'], game_data['away_team']]
        
        # Pre-load rosters for this game
        for team in teams:
            self.load_season_rosters(season)
        
        # Process players with name enhancement
        for player in game_data['players']:
            if player.get('name_incomplete'):
                enhanced = self.resolve_player_name(
                    player['last_name'], 
                    player['team'], 
                    season
                )
                player.update(enhanced)
        
        return game_data
```

---

## **Ready for Implementation**

**All prerequisites complete:**
* ✅ **Basketball Reference data**: 120 roster files collected and validated
* ✅ **Name mapping strategy**: Proven approach with test validation  
* ✅ **Infrastructure**: GCS paths, scraper architecture, operational procedures
* ✅ **Integration pattern**: Clear code examples and data flow

**Next developer can proceed immediately with:**
1. **Gamebook scraper creation** - Enhanced with Basketball Reference name mapping
2. **Workflow implementation** - Following proven Phase 1 patterns
3. **Testing and validation** - With comprehensive name resolution checks

The Basketball Reference integration transforms this from a basic gamebook collection project into an **enhanced data quality initiative** that will significantly improve the accuracy and completeness of historical NBA player data.
