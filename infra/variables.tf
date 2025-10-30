variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "ops_dataset_id" {
  type    = string
  default = "ops"
}

variable "precompute_service_name" {
  description = "Name of the precompute Cloud Run service"
  type        = string
  default     = "nba-precompute-service"
}

variable "cloud_run_region_hash" {
  description = "Cloud Run region hash (e.g., 'uw2' for us-west2)"
  type        = string
  default     = "uw2"  # Update based on your actual service URL
}