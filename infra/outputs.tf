output "ops_dataset" {
  value = google_bigquery_dataset.ops.self_link
}

output "scraper_runs_table" {
  value = google_bigquery_table.scraper_runs.self_link
}
