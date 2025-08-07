# NBA Gamebook PDF Scraper - Complete Documentation

## 🎯 **Overview**

The NBA Gamebook PDF Scraper extracts comprehensive player statistics and game data from official NBA gamebook PDFs for prop betting analysis. This system is designed for historical backfill (2021-2024 seasons) and ongoing data collection.

### **Key Features**
- ✅ **Full player statistics** (16+ fields per active player)
- ✅ **Game metadata** (arena, officials, attendance, duration)
- ✅ **Player availability status** (active/DNP/inactive with detailed reasons)
- ✅ **Production-ready logging** and monitoring
- ✅ **Batch processing** with parallel execution
- ✅ **Flexible date/season filtering**

---

## 📊 **Data Extracted**

### **Active Players** (Full Stats)
```json
{
  "name": "Jake LaRavia",
  "team": "Memphis Grizzlies",
  "status": "active",
  "stats": {
    "minutes": "40:00",
    "points": 32,
    "field_goals_made": 10,
    "field_goals_attempted": 18,
    "three_pointers_made": 8,
    "three_pointers_attempted": 11,
    "free_throws_made": 4,
    "free_throws_attempted": 5,
    "offensive_rebounds": 1,
    "defensive_rebounds": 6,
    "total_rebounds": 7,
    "assists": 1,
    "personal_fouls": 1,
    "steals": 2,
    "turnovers": 5,
    "blocks": 1,
    "plus_minus": -16,
    "field_goal_percentage": 0.556,
    "three_point_percentage": 0.727,
    "free_throw_percentage": 0.8
  }
}
```

### **DNP Players** (Did Not Play - Game Specific)
```json
{
  "name": "Santi Aldama",
  "team": "Memphis Grizzlies", 
  "status": "did_not_play",
  "dnp_reason": "NWT - Injury/Illness - Right Foot; Strain",
  "category": "NWT"
}
```

### **Inactive Players** (Longer-term Unavailable)
```json
{
  "name": "Morant",
  "team": "Memphis Grizzlies",
  "status": "inactive", 
  "reason": "Injury/Illness - Right Shoulder; Labral Repair",
  "category": "inactive"
}
```

### **Game Metadata**
```json
{
  "game_code": "20240410/MEMCLE",
  "date": "2024-04-10", 
  "matchup": "MEM@CLE",
  "arena": "Rocket Mortgage FieldHouse",
  "city": "Cleveland",
  "state": "OH",
  "officials": [
    {"number": 24, "name": "Kevin Scott"},
    {"number": 36, "name": "Brent Barnaky"},
    {"number": 41, "name": "Nate Green"}
  ],
  "attendance": 19432,
  "attendance_note": "Sellout",
  "game_duration": "2:10"
}
```

---

## 🏗️ **File Structure**

```
📁 nba-stats-scraper/
├── 📁 bin/backfill/
│   └── 📄 run_nba_gamebooks.sh          # Main runner script
├── 📁 scripts/
│   └── 📄 query_schedule.py             # Schedule filtering helper
├── 📁 scrapers/nbacom/
│   └── 📄 nbac_gamebook_pdf.py          # Core scraper implementation
└── 📁 workflows/backfill/
    └── 📄 collect-nba-gamebooks-external.yaml  # Cloud Workflows config
```

### **Component Descriptions**

| Component | Purpose | Key Features |
|-----------|---------|--------------|
| `nbac_gamebook_pdf.py` | Core scraper | PDF parsing, data extraction, validation |
| `run_nba_gamebooks.sh` | Batch runner | Parallel processing, date filtering, progress tracking |
| `query_schedule.py` | Schedule helper | Game code extraction from Phase 1 data |

---

## 🚀 **Usage Examples**

### **Single Game**
```bash
./bin/backfill/run_nba_gamebooks.sh --game_code "20240410/MEMCLE"
```

### **Single Date (All Games)**
```bash
./bin/backfill/run_nba_gamebooks.sh --date "2024-04-10"
```

### **Date Range**
```bash
./bin/backfill/run_nba_gamebooks.sh --start_date "2024-04-01" --end_date "2024-04-30"
```

### **Season + Team Filter**
```bash
./bin/backfill/run_nba_gamebooks.sh --season "2023-24" --team "MEM"
```

### **Full Season Backfill**
```bash
./bin/backfill/run_nba_gamebooks.sh --season "2023-24" --parallel 5
```

### **Dry Run (Preview)**
```bash
./bin/backfill/run_nba_gamebooks.sh --date "2024-04-10" --dry_run
```

---

## ⚙️ **Configuration Options**

### **Runner Script Options**
| Flag | Description | Example |
|------|-------------|---------|
| `--game_code` | Single game | `"20240410/MEMCLE"` |
| `--date` | Specific date | `"2024-04-10"` |
| `--start_date` / `--end_date` | Date range | `"2024-04-01"` / `"2024-04-30"` |
| `--season` | NBA season | `"2023-24"` |
| `--team` | Team filter | `"MEM"` |
| `--parallel` | Concurrent jobs | `5` (default: 3) |
| `--group` | Export target | `"prod"` (default), `"dev"` |
| `--dry_run` | Preview mode | Shows what would run |
| `--schedule_file` | Schedule data path | `"data/nba_schedule.json"` |

### **Scraper Parameters**
| Parameter | Description | Values |
|-----------|-------------|--------|
| `game_code` | Required game identifier | `"YYYYMMDD/AWAYTEAMHOMETEAM"` |
| `version` | PDF type | `"short"` (default), `"full"` |
| `group` | Export destination | `"prod"`, `"dev"`, `"capture"` |

---

## 📈 **Performance & Scale**

### **Data Metrics**
- **File size per game**: ~20KB JSON output
- **Full backfill (5,583 games)**: ~112MB total storage
- **Processing time**: ~10-15 seconds per game
- **Parallel processing**: 3-5 concurrent jobs recommended

### **Success Metrics**
```json
{
  "total_players": 41,
  "active_count": 21,
  "dnp_count": 6, 
  "inactive_count": 14,
  "parser_used": "pdfplumber"
}
```

### **Production Logging** (Clean & Efficient)
```
INFO: NBA Gamebook PDF URL (short): https://statsdmz.nba.com/pdfs/20240410/20240410_MEMCLE.pdf
INFO: pdfplumber extracted 3412 characters
INFO: Parsed game 20240410/MEMCLE: 21 active, 6 DNP, 14 inactive players (total: 41)
INFO: SCRAPER_STATS {"game_code": "20240410/MEMCLE", "total_players": 41, "arena": "Rocket Mortgage FieldHouse"}
```

---

## 🛠️ **Technical Implementation**

### **PDF Parsing Strategy**
1. **Download PDF** from `https://statsdmz.nba.com/pdfs/YYYYMMDD/YYYYMMDD_AWAYTEAMHOMETEAM.pdf`
2. **Extract text** using `pdfplumber` (clean, structured output)
3. **Parse players** by detecting minutes patterns (`XX:XX`) for active players
4. **Extract DNP/NWT** players from game-specific sections
5. **Parse inactive** players from bottom "Inactive:" sections
6. **Extract metadata** from PDF header (arena, officials, attendance)

### **Data Flow**
```
NBA PDF → pdfplumber → Text Extraction → Pattern Matching → JSON Structure → GCS Storage
```

### **Auto-Derivation from Game Code**
- `"20240410/MEMCLE"` automatically derives:
  - `date: "2024-04-10"`
  - `away_team: "MEM"`, `home_team: "CLE"`
  - `matchup: "MEM@CLE"`

---

## 🏀 **Prop Betting Analysis Value**

### **Primary Prop Markets**
- ✅ **Points** - Full scoring data + efficiency metrics
- ✅ **Rebounds** - Offensive, defensive, total rebounds
- ✅ **Assists** - Primary assist data
- ✅ **3-Pointers** - Made/attempted + percentage
- ✅ **Steals + Blocks** - Defensive statistics
- ✅ **Double-doubles** - Points + rebounds/assists combinations

### **Context Factors**
- ✅ **Minutes played** - Usage indicator for prop values
- ✅ **DNP reasons** - Injury/rest context for future games
- ✅ **Inactive players** - Long-term availability insights
- ✅ **Game environment** - Home/away, attendance, officials

### **Historical Analysis Power**
- **4 seasons** of comprehensive data (2021-2024)
- **Player trend analysis** across multiple seasons
- **Team context** and coaching decisions
- **Injury pattern recognition** from DNP/inactive reasons

---

## 🔧 **Setup & Installation**

### **Dependencies**
```bash
pip install pdfplumber
```

### **File Permissions**
```bash
chmod +x bin/backfill/run_nba_gamebooks.sh
chmod +x scripts/query_schedule.py
```

### **Directory Structure**
```bash
mkdir -p bin/backfill scripts
```

### **Validate Setup**
```bash
# Test single game
./bin/backfill/run_nba_gamebooks.sh --game_code "20240410/MEMCLE" --dry_run

# Check help
./bin/backfill/run_nba_gamebooks.sh --help
```

---

## 🚨 **Troubleshooting**

### **Common Issues**

#### **Schedule File Not Found**
```
Error: Schedule file not found: data/nba_schedule.json
```
**Solution**: Ensure Phase 1 (schedule collection) has been completed and schedule file exists.

#### **No Games Found**
```
No games found matching criteria
```
**Solution**: Check date format (`YYYY-MM-DD`) and verify games exist for specified date/season.

#### **PDF Parsing Failures**
```
ERROR: pdfplumber failed to extract any text from PDF
```
**Solution**: Check network connectivity and PDF URL accessibility. Some older games may have different PDF formats.

#### **Permission Errors**
```
Permission denied: ./bin/backfill/run_nba_gamebooks.sh
```
**Solution**: `chmod +x bin/backfill/run_nba_gamebooks.sh`

### **Debug Mode**
```bash
# Enable detailed logging
./bin/backfill/run_nba_gamebooks.sh --game_code "20240410/MEMCLE" --debug

# Check debug files
cat /tmp/debug_pdfplumber_text_*.txt
```

---

## 📊 **Monitoring & Validation**

### **Success Indicators**
- ✅ **Player counts make sense** (typically 20-25 total players per game)
- ✅ **Active players have stats** (minutes, points, percentages)
- ✅ **DNP reasons captured** (injury details, coaching decisions)
- ✅ **Game metadata complete** (arena, officials, attendance)

### **Data Quality Checks**
```bash
# Check player counts across multiple games
./bin/backfill/run_nba_gamebooks.sh --date "2024-04-10" | grep "total players"

# Validate JSON structure
cat /tmp/exp_*.json | jq '.total_players, .active_count, .dnp_count'
```

### **Log Monitoring**
Key log patterns to watch:
- `SCRAPER_STATS` - Final success metrics
- `Parsed game X: Y active, Z DNP, W inactive` - Core extraction success
- `pdfplumber extracted N characters` - PDF processing health

---

## 🔮 **Future Enhancements**

### **Planned Improvements**
1. **Name Resolution** - Basketball Reference integration for inactive player full names
2. **Advanced Stats** - PER, usage rate, efficiency metrics
3. **Multi-format Support** - Handle different PDF layouts across seasons
4. **Real-time Integration** - Live game processing during season

### **Integration Points**
- **Ball Don't Lie API** - Cross-validation of player stats
- **The Odds API** - Prop bet line correlation
- **Big Ball Data** - Enhanced play-by-play integration

---

## 📝 **Export Formats**

### **GCS Storage Paths**
```
nba-com/gamebooks-pdf/YYYY-MM-DD/game_YYYYMMDD_AWAYTEAMHOMETEAM/timestamp.pdf     # Original PDF
nba-com/gamebooks-data/YYYY-MM-DD/game_YYYYMMDD_AWAYTEAMHOMETEAM/timestamp.json   # Parsed data
```

### **Local Development**
```
/tmp/exp_[run_id].json      # Parsed JSON data
/tmp/raw_[run_id].pdf       # Original PDF
/tmp/debug_pdfplumber_text_[run_id].txt  # Debug text extraction
```

---

## 🎯 **Production Deployment**

### **Cloud Run Configuration**
- **Memory**: 1GB (PDF processing)
- **CPU**: 1 vCPU
- **Timeout**: 300 seconds
- **Concurrency**: 1 (sequential PDF processing)

### **Workflow Integration**
```yaml
# workflows/backfill/collect-nba-gamebooks-external.yaml
steps:
  - name: scrape_gamebook
    call: http.post
    args:
      url: ${SCRAPER_URL}
      body:
        game_code: ${game_code}
        group: "prod"
```

### **Monitoring Dashboards**
- **Success rate** by game/date
- **Processing time** trends
- **Data quality** metrics (player counts, missing fields)
- **Error patterns** and PDF parsing failures

---

## ✅ **Summary**

The NBA Gamebook PDF Scraper provides comprehensive player statistics and game data essential for prop betting analysis. With support for historical backfill, batch processing, and production monitoring, it serves as a robust foundation for NBA data collection.

**Key Strengths:**
- **Complete data extraction** (16+ stats per player)
- **Production-ready** logging and monitoring  
- **Scalable processing** (parallel execution)
- **Flexible filtering** (date, season, team)
- **Rich prop betting context** (DNP reasons, game environment)

**Ready for:**
- ✅ Historical backfill (2021-2024 seasons)
- ✅ Ongoing data collection
- ✅ Production deployment on Cloud Run
- ✅ Integration with prop betting analysis systems
