
resource "google_bigquery_table" "scraper_runs" {
  dataset_id = google_bigquery_dataset.ops.dataset_id
  table_id   = "scraper_runs"

  schema = jsonencode([
    { name = "process_id",  type = "STRING",  mode = "REQUIRED" },
    { name = "run_ts",      type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "status",      type = "STRING",  mode = "REQUIRED" },
    { name = "runtime_sec", type = "FLOAT",   mode = "NULLABLE" },
    { name = "row_count",   type = "INTEGER", mode = "NULLABLE" },
    { name = "file_uri",    type = "STRING",  mode = "NULLABLE" },
    { name = "error_msg",   type = "STRING",  mode = "NULLABLE" }
  ])

  time_partitioning {
    type  = "DAY"
    field = "run_ts"
  }

  clustering = ["process_id"]

  description = "One row per scraper attempt (STARTED / SUCCESS / FAILED)"
}


resource "google_bigquery_table" "process_tracking" {
  dataset_id = google_bigquery_dataset.ops.dataset_id
  table_id   = "process_tracking"

  schema = jsonencode([
    { name = "process_id",     type = "STRING",  mode = "REQUIRED" },
    { name = "entity_key",     type = "STRING",  mode = "REQUIRED" },
    { name = "version_handle", type = "STRING",  mode = "REQUIRED" },
    { name = "as_of_date",     type = "DATE",    mode = "NULLABLE" },
    { name = "arrived_at",     type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "row_count",      type = "INTEGER", mode = "NULLABLE" },
    { name = "file_uri",       type = "STRING",  mode = "NULLABLE" }
  ])

  time_partitioning {
    type  = "DAY"
    field = "arrived_at"
  }

  clustering = ["process_id", "entity_key"]

  description = "Version stamp for every successful ingest slice"
}


resource "google_bigquery_table" "player_report_runs" {
  dataset_id = google_bigquery_dataset.ops.dataset_id
  table_id   = "player_report_runs"

  schema = jsonencode([
    { name = "player_id",      type = "INTEGER",  mode = "REQUIRED" },
    { name = "game_id",        type = "STRING",   mode = "REQUIRED" },
    { name = "game_date",      type = "DATE",     mode = "REQUIRED" },
    { name = "status",         type = "STRING",   mode = "REQUIRED" },
    { name = "roster_v",       type = "STRING",   mode = "NULLABLE" },
    { name = "odds_v",         type = "STRING",   mode = "NULLABLE" },
    { name = "injury_v",       type = "STRING",   mode = "NULLABLE" },
    { name = "box_v",          type = "STRING",   mode = "NULLABLE" },
    { name = "pbp_v",          type = "STRING",   mode = "NULLABLE" },
    { name = "last_generated", type = "TIMESTAMP",mode = "REQUIRED" },
    { name = "grade_result",   type = "STRING",   mode = "NULLABLE" },
    { name = "actual_pts",     type = "INTEGER",  mode = "NULLABLE" },
    { name = "hit_minute",     type = "INTEGER",  mode = "NULLABLE" },
    { name = "report_uri",     type = "STRING",   mode = "NULLABLE" }
  ])

  time_partitioning {
    type  = "DAY"
    field = "game_date"
  }

  clustering = ["player_id"]

  description = "State‑machine & audit row per (player, game)"
}


resource "google_bigquery_table" "player_history_manifest" {
  dataset_id = google_bigquery_dataset.ops.dataset_id
  table_id   = "player_history_manifest"

  schema = jsonencode([
    { name = "player_id",        type = "INTEGER",  mode = "REQUIRED" },
    { name = "latest_hist_date", type = "DATE",     mode = "REQUIRED" },
    { name = "row_count",        type = "INTEGER",  mode = "NULLABLE" },
    { name = "updated_at",       type = "TIMESTAMP",mode = "REQUIRED" }
  ])

  time_partitioning {
    type  = "DAY"
    field = "updated_at"
  }

  clustering = ["player_id"]

  description = "Checkpoint of historical completeness per player"
}



