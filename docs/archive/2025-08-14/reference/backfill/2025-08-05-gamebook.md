# NBA Gamebook PDF Scraping Strategy
**Phase 2: Box Scores + DNP Reasons Collection**

## 🎯 **Project Goals**

### **Primary Objective**
Collect NBA gamebook PDFs to extract:
- ✅ **Complete box score statistics** for all players
- ✅ **DNP (Did Not Play) reasons** - **CRITICAL for prop betting context**
- ✅ **Inactive player information** with injury/rest details

### **Why This Matters**
- **Prop betting requires DNP context** - knowing WHY a player didn't play
- **Complete dataset** - box scores + context in one source
- **Historical backfill** - collect 2021-2024 seasons (~173k player records)

---

## 🏗️ **Architecture Strategy**

### **✅ Proven Infrastructure Approach**
- **Leverage existing schedule JSON data** (from Phase 1)
- **No web scraping dependency** (much more reliable!)
- **Single scraper per game** (follows established patterns)
- **External data preparation** (schedule extraction script)

### **✅ Data Sources**
- **Primary**: NBA.com official gamebook PDFs
- **URL Construction**: From existing schedule JSON (`gameCode` field)
- **Format**: `https://statsdmz.nba.com/pdfs/YYYYMMDD/YYYYMMDD_TEAMS.pdf`

---

## 📁 **File Structure & Implementation**

### **Core Files**
```
├── scrapers/nbacom/
│   └── nbac_gamebook_pdf.py              ← **Main scraper (Phase 2A)**
├── scripts/
│   └── extract_schedule_games.py         ← **Schedule data extractor**
├── workflows/backfill/
│   └── collect-nba-gamebooks-external.yaml ← **Orchestration workflow**
└── scrapers/utils/
    └── gcs_path_builder.py               ← **Update with new paths**
```

### **Future Expansion (Phase 2B)**
```
├── scrapers/nbacom/
│   ├── nbac_gamebook_pdf.py              ← **Short PDFs (box scores + DNP)**
│   └── nbac_gamebook_full_pdf.py         ← **Full PDFs (quarters + PBP)**
```

---

## 🚀 **Phased Implementation Strategy**

### **Phase 2A: Short PDFs (Immediate - DNP Focus)**
- **Target**: Basic box score PDFs (`.pdf` - NO `_book` suffix)
- **Content**: Final stats + DNP reasons + inactive players
- **Benefits**: Faster downloads, addresses immediate prop betting need
- **File**: `nbac_gamebook_pdf.py`

### **Phase 2B: Full PDFs (Future - Analytics)**
- **Target**: Detailed game books (`_book.pdf` suffix)
- **Content**: Quarter-by-quarter + play-by-play + enhanced stats
- **Benefits**: Deep analytics, quarter trends, detailed game flow
- **File**: `nbac_gamebook_full_pdf.py`

---

## 📊 **Data Storage Strategy**

### **✅ Dual Storage (Critical Decision)**
1. **Original PDFs** → `nba-com/gamebooks-pdf/YYYY-MM-DD/game_YYYYMMDD_TEAMS/timestamp.pdf`
2. **Parsed JSON** → `nba-com/gamebooks-data/YYYY-MM-DD/game_YYYYMMDD_TEAMS/timestamp.json`

### **✅ Why Store Both**
- **Debug parsing failures** - PDF structure changes over time
- **Re-parse with improved logic** - parsing will evolve
- **Historical preservation** - NBA may remove old PDFs
- **Compliance/audit** - original source documentation

---

## 🔄 **Workflow Architecture**

### **✅ External Schedule Loading (Much Better)**
1. **Schedule extraction script** reads existing JSON data
2. **Workflow orchestrates** individual scraper calls per game
3. **Single-game scraper** handles one PDF at a time
4. **Better error isolation** - one game fails, others continue

### **✅ Rate Limiting Strategy**
- **Conservative approach**: 5-second delays between games
- **Proxy support** for backfill operations
- **429 status code handling** with exponential backoff
- **Proven safe for NBA.com** based on research

---

## 🧪 **Testing Strategy**

### **Step 1: Individual Component Testing**
```bash
# Test schedule extraction
python scripts/extract_schedule_games.py \
    --date 2024-04-10 --season 2023 --output /tmp/test_games.json

# Test single scraper with capture.py
python tools/fixtures/capture.py nbac_gamebook_pdf \
    --date 2024-04-10 --game_code "20240410/MEMCLE" \
    --away_team MEM --home_team CLE --version short --debug
```

### **Step 2: Small Workflow Testing**
```bash
# Run workflow with 3-5 test games
gcloud workflows run collect-nba-gamebooks-external --location=us-west2
```

### **Step 3: Gradual Scaling**
- **Week 1**: 5-10 known games
- **Week 2**: 1 month of games  
- **Week 3**: Full season
- **Week 4**: All historical seasons

---

## 📋 **Implementation Checklist**

### **Tomorrow's Tasks**
- [ ] Create `nbac_gamebook_pdf.py` scraper
- [ ] Save `extract_schedule_games.py` in `scripts/`
- [ ] Update `gcs_path_builder.py` with new paths
- [ ] Test schedule extraction with known date
- [ ] Test scraper with capture.py tool
- [ ] Validate PDF parsing accuracy

### **This Week's Milestones**
- [ ] Deploy scraper to Cloud Run
- [ ] Test with sample of known games
- [ ] Validate DNP reason extraction
- [ ] Run small workflow test
- [ ] Document parsing accuracy

### **Next Week's Goals**
- [ ] Scale to full month backfill
- [ ] Monitor error rates and performance
- [ ] Optimize parsing logic based on results
- [ ] Plan Phase 2B (full PDFs) if needed

---

## 🎯 **Success Metrics**

### **Data Quality**
- **>95% game collection success rate**
- **>90% accurate DNP reason extraction**
- **Complete box score data** for active players

### **Performance**
- **<120 seconds** per workflow execution (similar to Phase 1)
- **Conservative rate limiting** maintains NBA.com good standing
- **Error resilience** - failed games don't stop workflow

### **Coverage**
- **Phase 2A Target**: 2024 season (test + validation)
- **Phase 2B Target**: 2021-2024 seasons (~173k player records)
- **Daily Operations**: Ongoing collection for new games

---

## 💡 **Key Strategic Decisions**

### **✅ Architecture Choices**
1. **Schedule JSON over web scraping** - much more reliable
2. **External data prep** - cleaner separation of concerns  
3. **Single scraper per game** - follows proven patterns
4. **Dual storage** - PDFs + parsed JSON for maximum value

### **✅ Implementation Approach**
1. **Start with short PDFs** - addresses immediate DNP need
2. **Conservative rate limiting** - maintains good standing
3. **Gradual scaling** - test → validate → scale
4. **Future-ready naming** - allows clean Phase 2B expansion

---

## 🚀 **Why This Strategy Works**

1. **✅ Leverages Proven Infrastructure** - builds on successful Phase 1
2. **✅ Addresses Critical Gap** - DNP reasons for prop betting
3. **✅ Minimizes Risk** - uses existing data, avoids web scraping
4. **✅ Scales Smoothly** - from test to full historical backfill
5. **✅ Future-Proof** - clean path to enhanced analytics (Phase 2B)

---

**Ready to implement Phase 2A tomorrow and solve the DNP context gap!** 🏀

---

*Generated: 2025-08-04 | Phase 2A Implementation Strategy*
