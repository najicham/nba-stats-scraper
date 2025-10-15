# NBA Workflow Schedule - Simple Reference

## 🕐 **Workflow Times**

| Workflow | Time (PT) | Frequency | Schedules |
|----------|-----------|-----------|-----------|
| **Morning Operations** | 8:00 AM | Daily | 1 trigger |
| **Real-Time Business** | 8 AM - 8 PM | Every 2 hours | 7 triggers |
| **Post-Game Collection** | 8:00 PM & 11:00 PM | Daily | 2 triggers |
| **Late Night Recovery** | 2:00 AM | Daily | 1 trigger |
| **Early Morning Final Check** | 6:00 AM | Daily | 1 trigger |

---

## 📋 **Scrapers by Workflow**

### **1. Morning Operations (8AM PT)**
*Daily setup + overnight recovery*
- `nbac_roster` - NBA Rosters
- `espn_roster_api` - ESPN Rosters
- `nbac_player_movement` - Player Movement
- `nbac_schedule_api` - NBA Schedule
- `bdl_standings` - BDL Standings
- `nbac_player_list` - Player List
- `nbac_injury_report` - Injury Report
- `pbp_enhanced_pbp` - Enhanced PBP Recovery
- **📝 Write execution status to GCS**

### **2. Real-Time Business (Every 2h: 8AM-8PM PT)**
*Revenue critical - Events → Props dependency*
- `oddsa_events` - Events API (**CRITICAL**)
- `oddsa_player_props` - Props API (**CRITICAL - depends on Events**)
- `nbac_player_list` - Player List
- `nbac_injury_report` - Injury Report
- `bdl_active_players` - BDL Players
- **📝 Write execution status to GCS**

### **3. Post-Game Collection (8PM & 11PM PT)**
*Same workflow with 2 schedulers - early games + late games*
- `espn_scoreboard_api` - ESPN Scoreboard
- `nbac_scoreboard_v2` - NBA Scoreboard
- `bdl_box_scores` - BDL Box Scores
- `bdl_player_box_scores` - Player Box Scores
- `espn_game_boxscore` - ESPN Game Boxscore (**depends on ESPN Scoreboard**)
- `bdl_live_box_scores` - BDL Live Scores
- `bdl_player_averages` - Player Averages
- `bdl_game_adv_stats` - Advanced Stats
- **📝 Write execution status to GCS**

### **4. Late Night Recovery (2AM PT)**
*Enhanced PBP + run all relevant scrapers (simple retry approach)*
- `pbp_enhanced_pbp` - Enhanced PBP
- `bdl_box_scores` - BDL Box Scores
- `bdl_player_box_scores` - Player Box Scores
- `bdl_player_averages` - Player Averages
- `bdl_game_adv_stats` - Advanced Stats
- `nbac_injury_report` - Injury Updates
- `nbac_player_movement` - Player Movement
- **📝 Write execution status to GCS**

### **5. Early Morning Final Check (6AM PT)**
*Last chance - run all critical scrapers*
- `pbp_enhanced_pbp` - Enhanced PBP Final Attempt
- `bdl_box_scores` - BDL Box Scores
- `bdl_player_box_scores` - Player Box Scores
- `bdl_player_averages` - Player Averages
- `bdl_game_adv_stats` - Advanced Stats
- `espn_scoreboard_api` - ESPN Scoreboard
- `espn_game_boxscore` - ESPN Game Boxscore (**depends on ESPN Scoreboard**)
- **📝 Write execution status to GCS**

---

## 🎯 **Critical Dependencies**

### **Revenue Critical (System Halts on Failure)**
- `oddsa_events` → `oddsa_player_props` (Real-Time Business only)

### **Data Dependencies (Retry on Failure)**
- `espn_scoreboard_api` → `espn_game_boxscore` (Post-Game, Early Morning Final Check)

### **All Other Scrapers**
- Non-critical (system continues on individual failures)
- Multiple recovery opportunities across workflows

---

## 📊 **Status Tracking & Recovery Strategy**

### **Status Files Written to GCS**
Each workflow writes execution results to:
```
/workflow-status/YYYY-MM-DD/workflow-name-HHhMMm.json
```

**Example:** `/workflow-status/2025-08-01/post-game-collection-20h15m.json`
```json
{
  "workflow": "post-game-collection",
  "execution_time": "2025-08-01T20:15:00Z",
  "scrapers": {
    "espn_scoreboard_api": {"status": "success", "duration": 12.3},
    "espn_game_boxscore": {"status": "failed", "error": "timeout"},
    "bdl_box_scores": {"status": "success", "duration": 45.1}
  }
}
```

### **Current Recovery Approach (Option 1)**
- **Simple**: Recovery workflows run ALL relevant scrapers
- **Reliable**: No complex logic, guaranteed coverage
- **Processor-handled**: Deduplication handled in data layer

### **Future Smart Recovery (Option 2)**
- **Foundation built**: Status files provide data for smart retry logic
- **Upgrade path**: Can implement selective retry when needed
- **Dependency-aware**: Will handle scraper chains intelligently

---

## 📊 **Data Collection Strategy**

- **Early games**: Collected at 8PM PT (East Coast games finished)
- **Late games**: Collected at 11PM PT (West Coast games finished)  
- **Enhanced PBP**: Available 2+ hours after game end (collected at 2AM/6AM)
- **Recovery**: Multiple attempts across 2AM and 6AM windows
- **Deduplication**: Handled by data processors, not workflows
- **Status tracking**: All execution results logged for future optimization
