
resource "google_bigquery_dataset" "ops" {
  dataset_id                 = var.ops_dataset_id
  location                   = var.region
  description                = "Operational & tracking tables for NBA prop pipeline"
  delete_contents_on_destroy = false
}

locals {
  ops_dataset = "${var.project_id}.${google_bigquery_dataset.ops.dataset_id}"
}
