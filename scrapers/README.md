# README: NBA / Odds API Scrapers

## Overview

This folder contains **Python scrapers** for NBA-related data (e.g., schedules, player movement, boxscores) and Odds API data (historical and current odds). All scrapers inherit from a central **`ScraperBase`** class that handles:

* **HTTP requests** (with optional proxy usage)
* **Automatic retries** for transient errors
* **Decoding** JSON or other data
* **Validation** (child classes provide domain-specific checks)
* **Exporting** data (to GCS, local files, etc.) via a **configurable exporter registry**
* **Logging** (structured logs for debugging and daily summary aggregation)

Each scraper can be run **locally** or deployed as a **Google Cloud Function**. Cloud Workflows can chain them together if you want orchestrated runs.

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

* **File**: `scraper_base.py`
* **Responsibilities**:

  1. **Option Validation**: Each child class declares `required_opts` (e.g. `["gamedate"]`). `ScraperBase` checks them before running.
  2. **`download_and_decode()`**: Handles HTTP GET (with retries, optional proxies). If decoding is set to JSON, automatically parses `self.decoded_data`.
  3. **`validate_download_data()`**: Child scrapers override to ensure required fields exist in `self.decoded_data`.
  4. **Exporting**: Based on each scraper’s `exporters` array (dicts specifying “type,” “key,” “groups,” etc.).
  5. **Structured Logging**: Outputs logs for downloads, retries, validation steps, plus a final `SCRAPER_STATS` line you can parse for daily summaries.
  6. **`post_export()`**: Hook method that logs final stats. By default, it merges default stats (runtime, scraper name) with any custom stats from `child_scraper.get_scraper_stats()`.

**Key Methods** Child scrapers might override:

* `set_url()`: Build the request URL from `self.opts`.
* `set_headers()`: Define any custom request headers.
* `validate_download_data()`: Ensure the final JSON structure is valid.
* `slice_data()`: If you want to transform or subset `self.decoded_data`, store results in `self.data[...]`.
* `should_save_data()`: Return `False` to skip export under certain conditions.
* `get_scraper_stats()`: Return a dict of custom fields (e.g. `records_found`) to include in the final `SCRAPER_STATS` log.

---

## Child Scrapers

Each scraper is named after its domain, e.g.:

1. **NBA.com** scrapers:

   * `nba_com_game_score.py`: Fetch NBA scoreboard data.
   * `nba_com_injury_report.py`: Parse the NBA’s injury report PDF.
   * `nba_com_player_boxscore.py`: Fetch daily player boxscores from stats.nba.com.
   * `nba_com_player_list.py`: Retrieve the current NBA player list.
   * `nba_com_player_movement.py`: Grab transaction/player movement data.
   * `nba_com_schedule.py`: Download and slice the NBA schedule.

2. **Odds API** scrapers:

   * `odds_api_historical_events.py`: Get historical NBA events for a given date/time.
   * `odds_api_player_props_history.py`: Fetch historical player props for a given event ID.
   * `odds_api_current_event_odds.py`: Get current odds/props for a given event ID.
   * `odds_api_team_players.py`: Fetch team/player rosters from The Odds API (undocumented endpoint).

**Each** scraper:

* Declares `required_opts` and optionally `additional_opts`.
* Has an `exporters` list specifying how to save data (GCS, file, Slack, etc.).
* Typically overrides `get_scraper_stats()` to return the number of records found, a `date` or `gamedate`, etc.

---

## Usage & Running Locally

1. **Install** dependencies in your virtualenv (see the project’s main `requirements.txt`).
2. **Activate** the venv:

   ```bash
   source .venv/bin/activate
   ```
3. **Run** a scraper locally:

   ```bash
   python nba_com_game_score.py --gamedate=2023-12-01 --group=dev
   ```

   or for an Odds API example:

   ```bash
   python odds_api_historical_events.py --apiKey=YOUR_KEY --date=2023-12-01T00:00:00Z
   ```
4. **Logs** print to console. The final line includes `SCRAPER_STATS {...}` with JSON you can parse.

*(You can pass extra flags or environment variables as needed, e.g. `ENV=local`.)*

---

## Deployment as GCF

Each scraper can be packaged as a **Google Cloud Function** (one per file) or you can create multiple GCFs from the same codebase:

1. **Example**:

   ```bash
   gcloud functions deploy NBAComGameScore \
     --runtime python310 \
     --entry-point GetNbaComGameScore \
     --trigger-http \
     --source .
   ```
2. **Environment** variables / secrets can be handled via GCF config, Secret Manager, or your CI/CD pipeline.

---

## Logging & Daily Summaries

* At the end of each run, **ScraperBase** logs `SCRAPER_STATS {...}` with:

  * `scraper_name`, `timestamp_utc`, `total_runtime`, etc.
  * Child-specific stats (e.g., `records_found`, `gamedate`) from `get_scraper_stats()`.
* **Cloud Logging** collects these lines. You can do a daily aggregator script (Cloud Scheduler + a small script) that:

  1. Queries logs for `textPayload:"SCRAPER_STATS"`
  2. Parses the JSON substring
  3. Merges them into a summary (by date, by scraper)
  4. Optionally sends Slack or email updates.

No extra JSON files or database needed—just parse logs once a day!

---

## Adding a New Scraper

1. **Create** a `.py` file in this directory, e.g. `my_new_scraper.py`.
2. **Subclass** `ScraperBase`, override:

   * `set_url()`: Build your request URL from `self.opts`.
   * `validate_download_data()`: Ensure you have the fields you expect in `self.decoded_data`.
   * `get_scraper_stats()`: Return any record counts, IDs, etc., to be included in the final stats log.
3. **Define** an `exporters` list specifying how/where to save data.
4. Optionally handle **`should_save_data()`** if you want to skip exporting under certain conditions.
5. **Test** locally, then deploy to GCF if needed.

---

## Conclusion

This directory hosts all scrapers that follow a **common** pattern:

* **`ScraperBase`** provides the framework (logging, retries, decoding, exporting).
* **Child classes** define domain logic: building URLs, validating results, collecting custom stats.
* **Exporters** let you store data in GCS, local files, or other destinations (Slack, etc.).
* **Logs** include a `SCRAPER_STATS` line, which you can parse daily for monitoring/summary.

Feel free to explore each scraper for specific usage examples and to add your own as new APIs or data sources arise!
