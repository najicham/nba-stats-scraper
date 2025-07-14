# infra/artifact_registry.tf
# Docker image registry for NBA Analytics platform

resource "google_artifact_registry_repository" "pipeline" {
  location      = var.region
  repository_id = "pipeline"
  description   = "NBA Analytics Docker images - base images and services"
  format        = "DOCKER"

  # Enable vulnerability scanning (free tier)
  docker_config {
    immutable_tags = false
  }

  labels = {
    environment = "production"
    team        = "nba-analytics" 
    purpose     = "container-images"
  }
}

# IAM permissions for Cloud Build to push images
resource "google_artifact_registry_repository_iam_member" "cloud_build_writer" {
  location   = google_artifact_registry_repository.pipeline.location
  repository = google_artifact_registry_repository.pipeline.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${data.google_project.project.number}@cloudbuild.gserviceaccount.com"
}

# IAM permissions for Cloud Run to pull images  
resource "google_artifact_registry_repository_iam_member" "cloud_run_reader" {
  location   = google_artifact_registry_repository.pipeline.location
  repository = google_artifact_registry_repository.pipeline.name
  role       = "roles/artifactregistry.reader" 
  member     = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
}

# Output the repository URL for use in build scripts
output "artifact_registry_url" {
  description = "Base URL for pushing Docker images"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.pipeline.repository_id}"
}

# Data source to get project info
data "google_project" "project" {}
