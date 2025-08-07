# BigDataBall Scrapers - Complete Documentation

## 📋 **Overview**

The BigDataBall scrapers provide access to enhanced NBA play-by-play data via Google Drive integration. The system consists of two optimized scrapers designed for the **discover game IDs → download specific game** workflow.

### **Key Features**
- ✅ **Enhanced Play-by-Play**: Sub-second timing, shot coordinates, real-time lineups
- ✅ **Clean JSON Output**: All NaN values converted to null for proper JSON
- ✅ **Game Metadata**: Teams, scores, dates extracted from filenames and data
- ✅ **Production Ready**: Cloud Run compatible with proper error handling
- ✅ **Props Analysis Ready**: Complete player performance tracking

## 🔍 **Discovery Scraper**

### **Purpose**
Fast discovery of available game IDs for targeted downloading (2-3 seconds).

### **Usage**
```bash
# Basic discovery for specific date
python tools/fixtures/capture.py bigdataball_discovery --date=2025-06-22

# With team filter
python tools/fixtures/capture.py bigdataball_discovery --date=2025-06-22 --teams=LAL

# Direct execution
python -m scrapers.bigdataball.bigdataball_discovery --date=2025-06-22 --group=dev
```

### **Output Structure**
```json
{
  "date": "2025-06-22",
  "timestamp": "2025-07-23T03:34:28.657782+00:00",
  "source": "bigdataball",
  "mode": "discovery",
  "results": {
    "count": 1,
    "games": [
      {
        "file_id": "1kAXcvezicVCMNDTAY3Byovev3yqF_KvE",
        "game_id": "0042400407",
        "teams": "IND@OKC",
        "away_team": "IND",
        "home_team": "OKC",
        "date": "2025-06-22"
      }
    ]
  }
}
```

## 📥 **Download Scraper**

### **Purpose**
Download specific games by ID or team matchup (3-5 seconds per game).

### **Usage**
```bash
# Download by game ID (RECOMMENDED)
python tools/fixtures/capture.py bigdataball_pbp --game_id=0042400407

# Download by team matchup
python tools/fixtures/capture.py bigdataball_pbp --teams="IND@OKC"

# Direct execution
python -m scrapers.bigdataball.bigdataball_pbp --game_id=0042400407 --group=dev
```

### **Output Structure**
```json
{
  "timestamp": "2025-07-23T03:57:51.782498+00:00",
  "source": "bigdataball",
  "game_info": {
    "game_id": "42400407",
    "date": "2025-06-22",
    "data_set": "NBA 2025 Playoffs",
    "away_team": "IND",
    "home_team": "OKC",
    "final_away_score": 91,
    "final_home_score": 103,
    "periods_played": 4
  },
  "file_info": {
    "name": "bigdataball_9e5da455_[2025-06-22]-0042400407-IND@OKC.csv",
    "total_plays": 510,
    "columns": 44
  },
  "playByPlay": [...]
}
```

## 🏀 **Play-by-Play Data Structure**

Each play contains up to 44 fields providing comprehensive game tracking:

### **Core Fields**
```json
{
  "game_id": 42400407,
  "date": "2025-06-22",
  "period": 1,
  "away_score": 0,
  "home_score": 0,
  "remaining_time": "0:12:00",
  "elapsed": "0:00:00",
  "play_id": 1,
  "event_type": "start of period"
}
```

### **Player Lineups (Real-time)**
```json
{
  "a1": "Myles Turner",           // Away position 1
  "a2": "Tyrese Haliburton",      // Away position 2
  "a3": "Andrew Nembhard",        // Away position 3
  "a4": "Aaron Nesmith",          // Away position 4
  "a5": "Pascal Siakam",          // Away position 5
  "h1": "Chet Holmgren",          // Home position 1
  "h2": "Jalen Williams",         // Home position 2
  "h3": "Luguentz Dort",          // Home position 3
  "h4": "Shai Gilgeous-Alexander", // Home position 4
  "h5": "Isaiah Hartenstein"      // Home position 5
}
```

### **Scoring Events**
```json
{
  "player": "Andrew Nembhard",
  "team": "IND",
  "event_type": "shot",
  "type": "jump shot",
  "points": 2.0,
  "result": "made",
  "shot_distance": 14.0,
  "original_x": 91.0,
  "original_y": 106.0,
  "description": "Nembhard 14' Pullup Jump Shot (2 PTS)"
}
```

### **Additional Tracking**
```json
{
  "assist": "Andrew Nembhard",    // Assisting player
  "block": "Aaron Nesmith",       // Blocking player
  "steal": null,                  // Stealing player
  "entered": "Player Name",       // Substitution in
  "left": "Player Name",          // Substitution out
  "num": 1.0,                     // Free throw number
  "outof": 2.0                    // Free throw attempts
}
```

## 🔧 **Data Validation with jq Commands**

### **Basic Structure Validation**
```bash
# Check overall JSON structure
jq 'keys' /tmp/bigdataball_game_42400407.json
# Output: ["file_info", "game_info", "playByPlay", "source", "timestamp"]

# Validate game metadata
jq '.game_info' /tmp/bigdataball_game_42400407.json

# Check file processing info
jq '.file_info | {name, total_plays, columns: (.columns | length)}' /tmp/bigdataball_game_42400407.json
```

### **Data Quality Checks**
```bash
# Verify no NaN values remain (should return nothing)
jq '.playByPlay[] | to_entries[] | select(.value == "NaN" or (.value | type == "string" and test("NaN")))' /tmp/bigdataball_game_42400407.json

# Check periods are valid (should be [1,2,3,4])
jq '.playByPlay | map(.period) | unique | sort' /tmp/bigdataball_game_42400407.json

# Verify play count
jq '.playByPlay | length' /tmp/bigdataball_game_42400407.json
```

### **Game Flow Validation**
```bash
# Check starting lineups
jq '.playByPlay[0] | {away: [.a1, .a2, .a3, .a4, .a5], home: [.h1, .h2, .h3, .h4, .h5]}' /tmp/bigdataball_game_42400407.json

# Validate final score
jq '.playByPlay | map(select(.event_type == "end of period")) | .[-1] | {period, away_score, home_score}' /tmp/bigdataball_game_42400407.json

# Count substitutions
jq '.playByPlay | map(select(.event_type == "substitution")) | length' /tmp/bigdataball_game_42400407.json
```

## 📊 **NBA Props Analysis Commands**

### **Player Performance Analysis**
```bash
# Count total scoring plays
jq '.playByPlay | map(select(.points != null)) | length' /tmp/bigdataball_game_42400407.json

# Player points summary (sorted by total points)
jq '.playByPlay | map(select(.points != null)) | group_by(.player) | map({player: .[0].player, total_points: (map(.points) | add), shots: length}) | sort_by(-.total_points)' /tmp/bigdataball_game_42400407.json

# Sample scoring plays
jq '.playByPlay | map(select(.points != null)) | .[0:3] | .[] | {player, points, shot_distance, result, description}' /tmp/bigdataball_game_42400407.json
```

### **Advanced Analytics**
```bash
# Shot location analysis
jq '.playByPlay | map(select(.shot_distance != null)) | .[0:3] | .[] | {player, shot_distance, original_x, original_y, result}' /tmp/bigdataball_game_42400407.json

# Assist tracking
jq '.playByPlay | map(select(.assist != null)) | .[0:5] | .[] | {player, assist, points, description}' /tmp/bigdataball_game_42400407.json

# Free throw analysis
jq '.playByPlay | map(select(.event_type == "free throw")) | .[0:3] | .[] | {player, result, num, outof, description}' /tmp/bigdataball_game_42400407.json
```

### **Prop-Specific Queries**
```bash
# Points props: Get all scoring events for specific player
jq '.playByPlay | map(select(.player == "Shai Gilgeous-Alexander" and .points != null)) | length' /tmp/bigdataball_game_42400407.json

# Assists props: Count assists for specific player
jq '.playByPlay | map(select(.assist == "Tyrese Haliburton")) | length' /tmp/bigdataball_game_42400407.json

# Three-point props: Filter 3-point shots
jq '.playByPlay | map(select(.points == 3.0)) | group_by(.player) | map({player: .[0].player, threes_made: length})' /tmp/bigdataball_game_42400407.json

# Free throw props: Count free throw makes/misses
jq '.playByPlay | map(select(.event_type == "free throw")) | group_by(.player) | map({player: .[0].player, made: (map(select(.result == "made")) | length), total: length})' /tmp/bigdataball_game_42400407.json
```

## 📈 **Sample Data Output**

### **Game Info Results**
```json
{
  "game_id": "42400407",
  "date": "2025-06-22", 
  "data_set": "NBA 2025 Playoffs",
  "away_team": "IND",
  "home_team": "OKC",
  "final_away_score": 91,
  "final_home_score": 103,
  "periods_played": 4
}
```

### **Player Performance Summary**
```json
[
  {"player": "Shai Gilgeous-Alexander", "total_points": 29, "shots": 39},
  {"player": "Bennedict Mathurin", "total_points": 24, "shots": 24},
  {"player": "Jalen Williams", "total_points": 20, "shots": 26},
  {"player": "Chet Holmgren", "total_points": 18, "shots": 16}
]
```

### **Shot Tracking Example**
```json
{
  "player": "Andrew Nembhard",
  "shot_distance": 14.0,
  "original_x": 91.0,
  "original_y": 106.0,
  "result": "made"
}
```

### **Assist Tracking Example**
```json
{
  "player": "Pascal Siakam",
  "assist": "Andrew Nembhard", 
  "points": 3.0,
  "description": "Siakam 25' 3PT Jump Shot (3 PTS) (Nembhard 1 AST)"
}
```

## 🚀 **Production Deployment**

### **Cloud Run Configuration**
```yaml
# For discovery service
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: bigdataball-discovery
spec:
  template:
    spec:
      containers:
      - image: gcr.io/project/bigdataball-discovery
        env:
        - name: BIGDATABALL_SERVICE_ACCOUNT_KEY_PATH
          value: "/secrets/bigdataball-key.json"
```

### **Google Workflows Integration**
```yaml
# Sample workflow step
- discovery:
    call: http.post
    args:
      url: ${discovery_service_url}
      body:
        date: ${date}
    result: discovery_result

- extract_games:
    assign:
      - games: ${discovery_result.body.results.games}

- download_games:
    for:
      value: game
      in: ${games}
      steps:
        - download:
            call: http.post
            args:
              url: ${download_service_url}
              body:
                game_id: ${game.game_id}
```

## 🎯 **NBA Props Use Cases**

### **Player Points Props**
- **Data Available**: Complete scoring tracking with shot locations
- **Analysis**: Points per game, shooting efficiency, shot distance analysis
- **Context**: Lineup combinations, game flow, clutch situations

### **Assists Props**  
- **Data Available**: Every assist attribution with recipient
- **Analysis**: Assist rates, player combinations, pick-and-roll effectiveness
- **Context**: Pace of play, teammate shooting performance

### **Shot Props (3PT, FG%)**
- **Data Available**: Every shot attempt with coordinates and distance
- **Analysis**: Shot charts, hot/cold zones, shot selection
- **Context**: Defensive matchups, game situation

### **Advanced Props**
- **Rebounds**: Track via substitution patterns and lineup analysis
- **Minutes**: Calculate from substitution events
- **Plus/Minus**: Score differential while player is on court

## 🔧 **Environment Setup**

### **Required Environment Variables**
```bash
# Google Drive service account
export BIGDATABALL_SERVICE_ACCOUNT_KEY_PATH="/path/to/service-account-key.json"

# Alternative using standard Google credentials
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
```

### **Dependencies**
```bash
pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib pandas
```

## 📝 **Data Freshness**

- **Update Frequency**: 2-3 hours after game completion
- **Availability**: Regular season and playoffs
- **Coverage**: Complete 2024-25 NBA season
- **Off-Season**: No new data (July-September)

## 🎯 **Performance Metrics**

- **Discovery**: 2-3 seconds (metadata only)
- **Download**: 3-5 seconds per game (~500-1000 plays)
- **Memory**: 50-100MB per individual game
- **Network**: 170KB per game file
- **Accuracy**: Official NBA data enhanced with coordinates

---

*Last Updated: July 23, 2025*  
*Data Source: BigDataBall Enhanced Play-by-Play via Google Drive*  
*Optimized for NBA Props Platform*
