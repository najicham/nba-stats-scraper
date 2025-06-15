````markdown

# Testing
$ python -m scrapers.espn_scoreboard --scoreDate 20231116
$ python -m scrapers.espn_roster_api --teamId 2 --group dev
$ python -m scrapers.espn_game_boxscore --gameId 401766123 --group dev --skip_json True


# README: NBA / Odds API Scrapers

## Overview

This folder contains **Python scrapers** for NBA-related data (e.g., schedules, player movement, boxscores) and Odds API data (historical and current odds). All scrapers inherit from a central **`ScraperBase`** class that handles:

- **HTTP requests** (with optional proxy usage)
- **Automatic retries** for transient errors
- **Decoding** JSON or other data (e.g., PDFs or raw bytes)
- **Validation** (child classes provide domain-specific checks)
- **Exporting** data (to GCS, local files, etc.) via a **configurable exporter registry**
- **Logging** (structured logs for debugging and daily summary aggregation)
- **Enums** for controlled “export modes” (`raw`, `decoded`, or `data`)

Each scraper can be run **locally** or deployed as a **Google Cloud Function**. You can also chain them in **Cloud Workflows** for orchestrated runs.

---

## Table of Contents

1. [ScraperBase Design](#scraperbase-design)
2. [Child Scrapers](#child-scrapers)
3. [Usage & Running Locally](#usage--running-locally)
4. [Deployment as GCF](#deployment-as-gcf)
5. [Logging & Daily Summaries](#logging--daily-summaries)
6. [Adding a New Scraper](#adding-a-new-scraper)

---

## ScraperBase Design

**Location**: [`scraper_base.py`](./scraper_base.py)

**Responsibilities**:

1. **Option Validation**  
   Each child class declares `required_opts` (e.g., `["gamedate"]`). `ScraperBase` checks them before running.

2. **`download_and_decode()`**  
   Handles HTTP GET with retries (and optional proxy). If `download_type` is JSON, it automatically decodes into `self.decoded_data`. Otherwise, you can parse it manually (e.g., PDFs).

3. **`validate_download_data()`**  
   Child scrapers override to ensure required fields exist in `self.decoded_data` (or the raw bytes).

4. **Exporting**  
   Each scraper’s `exporters` list specifies how to save data (e.g. GCS, file, Slack). Config fields like `"export_mode": "raw"` or `"decoded"` control whether the exporter receives bytes (`raw_response.content`), the JSON object (`decoded_data`), or a custom slice from `self.data`.

5. **Structured Logging**  
   Logs key steps (download, retries, validation) plus a final `SCRAPER_STATS` line you can parse for daily summaries. You can also override `post_export()` to add additional behaviors after exporting.

6. **Hooks** (e.g. `set_url()`, `transform_data()`, `should_save_data()`)  
   Child classes override these for domain-specific logic. That includes building URLs, deciding if data is valid, or slicing the final data for partial exports.

---

## Child Scrapers

### NBA.com Scrapers

- **`nba_com_game_score.py`**  
  Fetches the scoreboard data (scores/games) from NBA stats.

- **`nba_com_injury_report.py`**  
  Parses the NBA injury report PDF file.

- **`nba_com_player_boxscore.py`**  
  Retrieves per-player boxscores for a given date.

- **`nba_com_player_list.py`**  
  Retrieves the current list of all NBA players from the stats API.

- **`nba_com_player_movement.py`**  
  Fetches transaction / movement data (player trades, signings).

- **`nba_com_schedule.py`**  
  Downloads the full NBA schedule, then slices it by date/team to produce multiple exports.

### Odds API Scrapers

- **`odds_api_historical_events.py`**  
  Fetches historical odds events for a given date/time range.

- **`odds_api_player_props_history.py`**  
  Fetches historical player props for a given event ID.

- **`odds_api_current_event_odds.py`**  
  Retrieves current odds for a specific event (by sport + event ID).

- **`odds_api_team_players.py`**  
  Fetches a team’s player roster from an undocumented endpoint of The Odds API.

---

## Usage & Running Locally

1. **Install** dependencies from your `requirements.txt`:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
````

2. **Run** a scraper locally:

   ```bash
   cd scrapers
   python nba_com_game_score.py --gamedate=2023-12-01 --group=dev
   ```

   or for an Odds API example:

   ```bash
   python odds_api_historical_events.py --apiKey=MY_SECRET_KEY --date=2023-12-01T22:45:00Z
   ```

3. **Logs** appear in the console. The final line includes `SCRAPER_STATS {...}` with JSON you can parse for daily summaries.

4. **Options**:

   * `--group=dev` or `--group=prod` typically determines which exporters run.
   * Additional flags vary by scraper (e.g. `--gamedate`, `--apiKey`, etc.).

---

## Deployment as GCF

Each scraper can be deployed as a **Google Cloud Function**:

1. **Example**:

   ```bash
   gcloud functions deploy NbaComGameScore \
     --runtime python310 \
     --entry-point gcf_entry \
     --trigger-http \
     --source .
   ```

   * In your code, define a `gcf_entry(request)` function that instantiates the scraper, parses HTTP params, and calls `scraper.run(opts)`.

2. **Environment Variables**

   * If you rely on environment variables (like `SLACK_BOT_TOKEN`), set them via `gcloud functions deploy --set-env-vars ...` or use Secret Manager.

3. **Cloud Scheduler + Cloud Workflows**

   * You can schedule these GCF scrapers to run daily or orchestrate a workflow that calls multiple scrapers sequentially or in parallel.

---

## Logging & Daily Summaries

* **ScraperBase** logs a final line `SCRAPER_STATS { ... }` with:

  * Basic runtime fields: `run_id`, `scraper_name`, `timestamp_utc`, `total_runtime`
  * Child-specific stats from `get_scraper_stats()` (e.g., `records_found`, `gamedate`)

* **Parsing**

  * In GCP, these lines go into Cloud Logging. You can run a daily aggregator (another Cloud Function or local script) that:

    1. Queries logs for `textPayload:"SCRAPER_STATS"`.
    2. Extracts the JSON substring.
    3. Summarizes key fields (like `records_found`, `season`, `gamedate`).
    4. Optionally posts a Slack or email summary.

No need for extra DB tables or JSON files—just parse the logs once a day for a simple “what ran and what it found” summary.

---

## Adding a New Scraper

1. **Create** a `.py` file, e.g. `my_new_scraper.py`.

2. **Subclass** `ScraperBase`:

   ```python
   from .scraper_base import ScraperBase

   class MyNewScraper(ScraperBase):
       required_opts = ["some_required_arg"]
       additional_opts = []

       exporters = [
         {
           "type": "gcs",
           "key": "my/new/data/%(some_required_arg)s/%(time)s.json",
           "export_mode": "raw",
           "groups": ["prod", "gcs"],
         },
         {
           "type": "file",
           "filename": "/tmp/my_new_data.json",
           "export_mode": "decoded",
           "groups": ["dev", "file"],
         }
       ]

       def set_url(self):
           self.url = f"https://example.com/api?arg={self.opts['some_required_arg']}"

       def validate_download_data(self):
           if "someKey" not in self.decoded_data:
               raise DownloadDataException("Missing 'someKey' in response.")

       def get_scraper_stats(self):
           return {
               "records_found": len(self.decoded_data["someKey"]),
               "some_required_arg": self.opts.get("some_required_arg")
           }
   ```

3. **Test** it locally. Then you can deploy to GCF if needed.

4. **Profit**—the new scraper reuses the standard logic for retries, logging, exporting, etc.

---

## Conclusion

This directory contains all scrapers following a **common** pattern:

* **`ScraperBase`** orchestrates the lifecycle: (options → download → decode → validate → export → final stats).
* **Child scrapers** override domain-specific methods (URL building, validations, data slicing).
* **Exporters** store data in GCS, local files, Slack, etc., controlled by each scraper’s `exporters` array.
* A final **`SCRAPER_STATS`** line in logs can be used for daily summary and monitoring.

Feel free to explore each file for usage examples or create your own new scrapers. Happy scraping!
