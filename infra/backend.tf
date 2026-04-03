# Terraform remote state backend
# Session 509: Added to prevent state loss (previously local-only).
#
# To migrate existing local state to GCS:
#   1. Create the bucket: gsutil mb -p nba-props-platform -l us-west2 gs://nba-props-platform-terraform-state
#   2. Enable versioning:  gsutil versioning set on gs://nba-props-platform-terraform-state
#   3. Run: terraform init -migrate-state
#
# After migration, state is stored in GCS with versioning — safe to run from any machine.

terraform {
  backend "gcs" {
    bucket = "nba-props-platform-terraform-state"
    prefix = "infra"
  }
}
