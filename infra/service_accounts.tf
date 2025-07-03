
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
