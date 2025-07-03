
#########################################################
#  IAM POLICY FOR  ops  BIGQUERY DATASET
#########################################################

# 1. Workflow needs to INSERT/UPDATE rows in ops.scraper_runs
resource "google_bigquery_dataset_iam_member" "wf_ops_editor" {
  dataset_id = google_bigquery_dataset.ops.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.workflow_sa.email}"
}

# 2. Processor writes ops.process_tracking
resource "google_bigquery_dataset_iam_member" "processor_ops_editor" {
  dataset_id = google_bigquery_dataset.ops.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.processor_sa.email}"
}

# 3. Report generator reads ops tables & writes player_report_runs
resource "google_bigquery_dataset_iam_member" "reportgen_ops_editor" {
  dataset_id = google_bigquery_dataset.ops.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.reportgen_sa.email}"
}

# 4. Analyst group gets read‑only
# resource "google_bigquery_dataset_iam_member" "ops_viewer_group" {
#   dataset_id = google_bigquery_dataset.ops.dataset_id
#   role       = "roles/bigquery.dataViewer"
#   member     = "group:analysts@yourcompany.com"   # replace with real group or comment out
# }
