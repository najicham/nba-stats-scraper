
#########################################################
#  SERVICE ACCOUNTS (created and managed by Terraform)
#########################################################

resource "google_service_account" "workflow_sa" {
  account_id   = "workflow-sa"
  display_name = "Workflow orchestrator SA"
}

resource "google_service_account" "processor_sa" {
  account_id   = "processor-sa"
  display_name = "Ingest processor SA"
}

resource "google_service_account" "reportgen_sa" {
  account_id   = "reportgen-sa"
  display_name = "Report generator SA"
}

# Phase 4 Precompute Permissions
resource "google_project_iam_member" "processor_sa_bigquery_precompute_write" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.processor_sa.email}"
}

resource "google_project_iam_member" "processor_sa_bigquery_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.processor_sa.email}"
}

# Note: Pub/Sub permissions are granted in pubsub.tf