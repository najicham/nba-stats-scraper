# Data Validator Requirements Template

**Purpose:** This template lists all information needed to build a comprehensive data validator for any processor/data source.

**Instructions:** 
1. Copy this template for your specific processor
2. Fill in all sections marked with `[FILL IN]`
3. Check all boxes as you provide information
4. Share completed document with validation team

---

## 📌 Basic Information

**Processor Name:** `[FILL IN: e.g., odds_api_game_lines]`  
**Data Source:** `[FILL IN: e.g., The Odds API, ESPN, NBA.com]`  
**Data Type:** `[SELECT: Raw Scraper Data / API Data / Analytics Table / Reference Data]`  
**Point of Contact:** `[FILL IN: Name/Email]`  
**Target Validator:** `validation/validators/[layer]/[processor_name]_validator.py`  
**Target Config:** `validation/configs/[layer]/[processor_name].yaml`

**Data Description:**  
`[FILL IN: 2-3 sentence description of what this data represents and why it's important]`

**Example:**
> Odds API Game Lines captures betting lines (spread, moneyline, total) from multiple sportsbooks for NBA games. This data is critical for prop bet analysis, value identification, and model training.

---

## 1️⃣ BigQuery Schema Information

### Table Details
- [ ] **Full table name:** `[FILL IN: e.g., nba-props-platform.nba_raw.table_name]`
- [ ] **Is table partitioned?** `[YES/NO]`
  - If YES, **partition field:** `[FILL IN: e.g., game_date]`
  - If YES, **partition type:** `[DAY/MONTH/YEAR/TIMESTAMP]`
- [ ] **Is `require_partition_filter = true`?** `[YES/NO]`
- [ ] **Cluster fields:** `[FILL IN or write "None"]`
- [ ] **Table description:** `[FILL IN: Brief description from schema]`

### Schema Fields

**Please provide the complete schema.** Either:

**Option A: Paste CREATE TABLE statement:**
```sql
[PASTE YOUR FULL CREATE TABLE STATEMENT HERE]
```

**Option B: Run this query and paste results:**
```sql
SELECT 
  column_name,
  data_type,
  is_nullable,
  description
FROM `[PROJECT_ID].[DATASET].INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = '[TABLE_NAME]'
ORDER BY ordinal_position;
```

### Key Field Questions
- [ ] **Game identifier field:** `[FILL IN: e.g., game_id]`
- [ ] **Date field:** `[FILL IN: e.g., game_date]`
- [ ] **Processing timestamp field:** `[FILL IN: e.g., processed_at]`
- [ ] **Team identifier fields:** `[FILL IN: e.g., home_team_abbr, away_team_abbr]`
  - Format: `[abbreviation/tricode/full name/id]`
- [ ] **Unique record identifier:** `[FILL IN: What uniquely identifies a row?]`
  - Example: `game_id + bookmaker + market` OR `player_id + game_id`
- [ ] **Any JSON/ARRAY fields?** `[List them or write "None"]`
- [ ] **Any ENUM/categorical fields?** `[List field names]`

---

## 2️⃣ GCS Storage Information

### Bucket Structure
- [ ] **GCS bucket name:** `[FILL IN: e.g., gs://nba-props-platform-scrapers]`
- [ ] **Base path:** `[FILL IN: e.g., odds_api/game_lines/]`
- [ ] **File naming pattern:** `[FILL IN: e.g., {date}/game_lines_{timestamp}.json]`
- [ ] **File format:** `[JSON/JSONL/CSV/Parquet/Other]`
- [ ] **File organization:** `[By date/By season/By team/Flat/Other]`

**Complete example path:**
```
[FILL IN: gs://bucket/path/to/2024-10-22/filename_pattern.json]
```

### File Details
- [ ] **Typical file size range:** `[FILL IN: e.g., 50KB - 2MB]`
- [ ] **Files per day:** `[FILL IN: e.g., 1 file, multiple snapshots, varies]`
- [ ] **Multiple files per day?** `[YES/NO]`
  - If YES, explain pattern: `[e.g., one per game, one per hour, etc.]`
- [ ] **Sentinel/marker files?** `[YES/NO]`
  - If YES, describe: `[e.g., _SUCCESS file after completion]`

### File Content
**Please provide sample file content (first 20-50 lines):**
```bash
# Run this and paste output:
gsutil cat gs://[your-bucket]/[path-to-sample-file] | head -50
```

Or paste sample here:
```json
[PASTE SAMPLE FILE CONTENT]
```

---

## 3️⃣ Data Coverage & Expectations

### Historical Coverage
- [ ] **Earliest date with data:** `[FILL IN: YYYY-MM-DD]`
- [ ] **Latest date with data:** `[FILL IN: YYYY-MM-DD or "Current"]`
- [ ] **Which seasons have data?**
  - [ ] 2021-22 (Oct 2021 - Jun 2022)
  - [ ] 2022-23 (Oct 2022 - Jun 2023)
  - [ ] 2023-24 (Oct 2023 - Jun 2024)
  - [ ] 2024-25 (Oct 2024 - Current)
  - [ ] Other: `[FILL IN]`

### Data Refresh Cadence
- [ ] **How often is data collected?**
  - [ ] Daily (once per day)
  - [ ] Multiple times per day (specify: `[e.g., every 4 hours]`)
  - [ ] Real-time/continuous
  - [ ] Weekly
  - [ ] Other: `[FILL IN]`

- [ ] **When does data arrive after game/event?**
  - [ ] Before game starts
  - [ ] During game (live)
  - [ ] After game completes
  - [ ] Next day
  - [ ] Delayed by: `[FILL IN: e.g., 2 hours]`

### Expected Record Counts

**For a typical regular season day with 10 games, how many records expected?**
`[FILL IN: e.g., "100 records (10 games × 10 bookmakers)" or "10 records (1 per game)"]`

**Total records per season (estimated):**
```yaml
# Fill in actual or estimated counts
2021-22: [FILL IN]
2022-23: [FILL IN]
2023-24: [FILL IN]
2024-25: [FILL IN] (or "in progress")
```

### Game/Event Coverage
- [ ] **What games/events should have data?**
  - [ ] Regular season only
  - [ ] Playoffs
  - [ ] Preseason
  - [ ] All-Star
  - [ ] Other: `[FILL IN]`

- [ ] **Are all games expected to have data?** `[YES/NO/VARIES]`
  - If VARIES, explain: `[e.g., only nationally televised games]`

- [ ] **Any systematic exclusions?**
  - [ ] Postponed games
  - [ ] Cancelled games
  - [ ] International games
  - [ ] Other: `[FILL IN]`

---

## 4️⃣ Data Quality Rules

### Required Fields (Never Null)
**Which fields should ALWAYS have values?**

- [ ] `[List field names, one per line]`
- [ ] 
- [ ] 
- [ ] 

### Valid Ranges
**For numeric fields, what are acceptable ranges?**

| Field Name | Minimum | Maximum | Notes |
|------------|---------|---------|-------|
| `[FILL IN]` | `[FILL IN]` | `[FILL IN]` | `[Optional notes]` |
| `[FILL IN]` | `[FILL IN]` | `[FILL IN]` | |

**Examples:**
- `points_scored`: 0 to 200
- `spread`: -30 to +30
- `confidence_score`: 0.0 to 1.0

### Categorical/Enum Values
**For categorical fields, what are valid values?**

**Field: `[FILL IN field name]`**
Valid values:
```
[FILL IN: List all valid values, one per line]
```

**Example:**
- Field: `market`
- Valid values: `spreads`, `h2h`, `totals`

### Team Names/Identifiers
- [ ] **Team identifier format:** `[abbreviation/tricode/full name/id/other]`
- [ ] **Valid team values:**
```
[FILL IN: List all valid team names/codes]
Example: ATL, BOS, BKN, CHA, CHI, CLE, DAL, DEN, DET, GSW, HOU, IND, LAC, LAL, MEM, MIA, MIL, MIN, NOP, NYK, OKC, ORL, PHI, PHX, POR, SAC, SAS, TOR, UTA, WAS
```

### Uniqueness Constraints
**What combination of fields should be unique?**
`[FILL IN: e.g., "game_id + bookmaker + market" should be unique per snapshot]`

---

## 5️⃣ Known Issues & Edge Cases

### Data Gaps
- [ ] **Are there known date gaps?** `[YES/NO]`
  - If YES, list dates/ranges: `[FILL IN]`

- [ ] **Any systematic data quality issues?** `[YES/NO]`
  - If YES, describe: `[FILL IN]`

### Processing Issues
- [ ] **Maximum expected processing lag:** `[FILL IN: e.g., "Data should arrive within 2 hours of game end"]`
- [ ] **Are duplicates possible?** `[YES/NO]`
  - If YES, how to deduplicate: `[FILL IN: e.g., "Take most recent by processed_at"]`

### Historical Changes
- [ ] **Has data format changed over time?** `[YES/NO]`
  - If YES, describe: `[FILL IN: e.g., "Added new field X in 2023-24 season"]`

- [ ] **Any provider/source changes?** `[YES/NO]`
  - If YES, describe: `[FILL IN]`

### Edge Cases
**Describe any special situations to be aware of:**
```
[FILL IN: 
- Example: Some games don't have odds if line is pulled
- Example: Playoff games may have delayed data
- etc.]
```

---

## 6️⃣ Cross-Validation Sources

### Reference Tables
**Which tables should we cross-validate against?**

- [ ] **Schedule table:** `[FILL IN table name or "N/A"]`
  - Purpose: `[e.g., Ensure all completed games have data]`
  
- [ ] **Team reference:** `[FILL IN table name or "N/A"]`
  - Purpose: `[e.g., Validate team names/IDs]`
  
- [ ] **Related data table:** `[FILL IN table name or "N/A"]`
  - Purpose: `[e.g., Cross-check with boxscore data]`

### Cross-Validation Rules
**What relationships should hold true?**

```
[FILL IN: 
- Example: Every completed regular season game in schedule should have odds data
- Example: Every player in boxscore should exist in player registry
- Example: Game dates should match between this table and schedule
- etc.]
```

### Join Keys
**How should we join with reference tables?**

```
[FILL IN:
- To join with schedule: ON this_table.game_id = schedule.game_id AND this_table.game_date = schedule.game_date
- To join with teams: ON this_table.team_abbr = teams.team_tricode
- etc.]
```

---

## 7️⃣ Sample Data & Queries

### Sample Records
**Please provide 5-10 representative rows:**

```sql
SELECT *
FROM `[PROJECT_ID].[DATASET].[TABLE_NAME]`
WHERE game_date = '[RECENT_DATE]'
LIMIT 10;
```

**Paste results here:**
```
[PASTE QUERY RESULTS]
```

### Record Counts by Date
**Please provide recent daily counts:**

```sql
SELECT 
  game_date,
  COUNT(*) as total_records,
  COUNT(DISTINCT [KEY_FIELD]) as unique_items,
  MIN(processed_at) as first_processed,
  MAX(processed_at) as last_processed
FROM `[PROJECT_ID].[DATASET].[TABLE_NAME]`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY game_date
ORDER BY game_date DESC;
```

**Paste results here:**
```
[PASTE QUERY RESULTS]
```

### Data Distribution
**Provide any relevant distribution queries:**

```sql
[EXAMPLE: For categorical fields, show counts per category]
SELECT 
  [CATEGORICAL_FIELD],
  COUNT(*) as count
FROM `[PROJECT_ID].[DATASET].[TABLE_NAME]`
WHERE game_date >= '[RECENT_DATE]'
GROUP BY [CATEGORICAL_FIELD]
ORDER BY count DESC;
```

**Paste results here:**
```
[PASTE QUERY RESULTS]
```

---

## 8️⃣ Processor Information

### Processor Details
- [ ] **Processor name:** `[FILL IN: e.g., odds_api_game_lines_processor]`
- [ ] **Processor file location:** `[FILL IN: e.g., data_processors/raw/odds_api/game_lines_processor.py]`
- [ ] **Scraper file location (if applicable):** `[FILL IN or "N/A"]`

### Processing Logic
**Describe any important transformations:**
```
[FILL IN:
- Does processor rename fields?
- Does processor filter/exclude any data?
- Does processor aggregate or compute derived fields?
- Does processor deduplicate?
- etc.]
```

### Dependencies
- [ ] **Depends on other processors?** `[YES/NO]`
  - If YES, list: `[FILL IN: e.g., requires schedule to be processed first]`

---

## 9️⃣ Backfill/Timeline Information

### Backfill Details
- [ ] **Is this a new backfill?** `[YES/NO]`
- [ ] **Date range being backfilled:** `[FILL IN: YYYY-MM-DD to YYYY-MM-DD]`
- [ ] **Estimated completion date:** `[FILL IN or "In progress"]`
- [ ] **Backfill approach:** `[All at once / In batches / Incremental]`
  - If batches, describe: `[e.g., One season at a time]`

### Validation Timing
- [ ] **When should validator run?**
  - [ ] After backfill completes
  - [ ] Incrementally during backfill
  - [ ] Daily going forward
  - [ ] Other: `[FILL IN]`

---

## 🔟 Success Criteria

### Quality Thresholds
**What defines "good quality" data?**

- [ ] **Completeness:** `[FILL IN: e.g., >= 95% of expected games have data]`
- [ ] **Timeliness:** `[FILL IN: e.g., Data should arrive within 4 hours]`
- [ ] **Accuracy:** `[FILL IN: Any accuracy measures?]`
- [ ] **Coverage:** `[FILL IN: Any coverage requirements?]`

### Validation Priorities
**Rate the importance of each validation type:**

| Validation Type | Priority (High/Medium/Low) | Notes |
|----------------|---------------------------|-------|
| Record counts match expected | `[FILL IN]` | |
| No missing games | `[FILL IN]` | |
| No null required fields | `[FILL IN]` | |
| Values in valid ranges | `[FILL IN]` | |
| Cross-validation with schedule | `[FILL IN]` | |
| GCS files exist | `[FILL IN]` | |
| Data freshness | `[FILL IN]` | |
| Other: `[FILL IN]` | `[FILL IN]` | |

### Alerting Preferences
- [ ] **When should we alert?**
  - [ ] Any validation failure
  - [ ] Only critical failures
  - [ ] Only after N consecutive failures
  - [ ] Other: `[FILL IN]`

- [ ] **Who should be notified?**
  - Email: `[FILL IN]`
  - Slack channel: `[FILL IN]`

---

## ✅ Checklist Summary

**Before submitting, verify you've provided:**

- [ ] Basic information (processor name, data source, description)
- [ ] Complete BigQuery schema or CREATE TABLE statement
- [ ] GCS bucket paths and file patterns
- [ ] Sample data (at least 10 rows)
- [ ] Expected record counts and coverage
- [ ] Data quality rules (required fields, valid ranges)
- [ ] Cross-validation requirements
- [ ] Known issues and edge cases
- [ ] Processor location and transformation details
- [ ] Success criteria and alerting preferences

---

## 📊 Priority Information

### Must Have (Critical - Needed to Start)
1. ✅ BigQuery table name and partition details
2. ✅ GCS bucket path and file pattern  
3. ✅ Key field names (date, game_id, teams, etc.)
4. ✅ Sample data (10 rows)
5. ✅ Required fields (never null)

### Should Have (Important - Needed for Complete Validator)
6. Expected data coverage and counts
7. Valid ranges for numeric fields
8. Cross-validation source tables
9. Known issues and edge cases

### Nice to Have (Improves Quality)
10. Processor transformation details
11. Detailed success criteria
12. Historical context and changes
13. Performance/timing requirements

---

## 💬 Questions or Clarifications?

**If you're unsure about any section:**
- Mark it as `[NEED CLARIFICATION: reason]`
- The validation team will help fill in gaps
- It's okay to not have all answers immediately

**Contact:**
- Validation team: `[FILL IN contact method]`
- Project lead: `[FILL IN contact method]`

---

## 🎯 Next Steps

1. ✅ Fill out this template completely
2. ✅ Run the sample queries and paste results  
3. ✅ Share completed document with validation team
4. ⏳ Validation team builds validator (30-60 minutes)
5. ✅ Test validator on your data
6. ✅ Iterate based on results
7. 🚀 Deploy to production

**Estimated timeline from info → working validator: 1-2 hours**

---

*Template Version: 1.0*  
*Last Updated: 2025-10-10*