# BigDataBall Play-by-Play - Discovery Phase

**FILE:** `validation/queries/raw/bigdataball_pbp/discovery/DISCOVERY_SUMMARY.md`

---

## 🚨 MANDATORY: Run Discovery Queries First!

Before creating validation queries, we must understand what data actually exists.

---

## Discovery Queries to Run (in order)

### 1️⃣ Discovery Query 1: Actual Date Range
**Purpose:** Find min/max dates, total events, unique games
**What to document:**
```
Earliest Date: ___________
Latest Date: ___________
Total Games: ___________
Avg Events Per Game: ___________
```

### 2️⃣ Discovery Query 2: Event Volume by Date
**Purpose:** Check for anomalies in event counts
**What to look for:**
- Are most games 400-600 events?
- Any dates with critically low counts (<300)?
- Any suspiciously high counts (>700)?

### 3️⃣ Discovery Query 3: Missing Game Days vs Schedule
**Purpose:** Find which scheduled game dates have NO play-by-play data
**What to document:**
```
Number of missing dates: ___________
Pattern identified (if any): ___________
```

### 4️⃣ Discovery Query 4: Date Continuity Gaps
**Purpose:** Identify large gaps in date coverage
**What to look for:**
- Off-season gaps (June-Oct): 90-130 days = NORMAL
- All-Star break: 6-7 days = EXPECTED
- Any other gaps >7 days = INVESTIGATE

### 5️⃣ Discovery Query 5: Event Sequence Integrity
**Purpose:** Check if event sequences are complete per game
**What to look for:**
- Do sequences start at 0 or 1?
- Are there gaps in sequence numbers?
- Any duplicate sequences?

---

## Next Steps

After running all 5 queries, document your findings:

**DISCOVERY FINDINGS TEMPLATE**
```
Data Source: BigDataBall Play-by-Play
Table: nba-props-platform.nba_raw.bigdataball_play_by_play

Actual Date Range: [min_date] to [max_date]
Total Dates: [count] dates with data
Total Events: [count] total records
Unique Games: [count] games
Avg Events Per Game: [count] events

Missing Dates: [count] dates missing
Patterns Identified: [All-Star weekends, specific gaps, etc.]
Coverage Assessment: [X%] complete

Event Sequence Status: [Complete/Issues found]
Data Quality Flags: [Any anomalies from queries 2-5]

Date Ranges for Validation Queries:
- Full range: [start] to [end]
- Current season: [start] to [end]
- Historical: [start] to [end]
```

---

## Questions to Answer

1. **How many seasons do you actually have?**
   - Processor reference says: 2024-25 only
   - You mentioned: 4 seasons (2021-2025)
   - Discovery Query 1 will tell us the truth

2. **Is coverage complete?**
   - Discovery Query 3 will show missing game dates

3. **Are event counts reasonable?**
   - Discovery Query 2 will show average ~400-600 events per game

4. **Is data quality good?**
   - Discovery Query 5 will check event sequence integrity

---

## After Discovery: Next Steps

Once you've run the queries and documented findings, I'll create:

✅ **Season Completeness Check** (adapted from BDL)
✅ **Find Missing Games** (adapted from BDL)  
✅ **Daily Check Yesterday** (adapted from BDL)
✅ **Weekly Check Last 7 Days** (adapted from BDL)
✅ **Event Quality Checks** (play-by-play specific)
✅ **CLI Tool** (for easy daily validation)

**Please run the 5 discovery queries and share results!**
