# ============================================================================
# Cloud Run Services and Workflows
# ============================================================================
# 
# Status: PARTIALLY DISABLED - Some resources commented out pending setup
# 
# Active Resources:
# - Secret Manager for Odds API key
# 
# Commented Out (to be enabled later):
# - Cloud Run services (need Docker images built first)
# - Workflows (need workflow YAML file created)
# - Cloud Build trigger (optional - for CI/CD)
# ============================================================================

# ----------------------------------------------------------------------------
# Secret Manager for API Keys
# ----------------------------------------------------------------------------

resource "google_secret_manager_secret" "odds_api_key" {
  secret_id = "odds-api-key"
  project   = var.project_id
  
  replication {
    auto {}
  }

  labels = {
    service = "scrapers"
    phase   = "phase1"
  }
}

# ----------------------------------------------------------------------------
# Cloud Run Services - COMMENTED OUT
# ----------------------------------------------------------------------------
# 
# Uncomment these after:
# 1. Building Docker images: gcr.io/nba-props-platform/nba-scraper-events:latest
# 2. Creating nba_scraper service account OR using workflow_sa
# 
# ----------------------------------------------------------------------------

# resource "google_cloud_run_service" "nba_scraper_events" {
#   name     = "nba-scraper-events"
#   location = var.region
#   project  = var.project_id
# 
#   template {
#     spec {
#       service_account_name = google_service_account.workflow_sa.email  # Using workflow_sa
#       
#       containers {
#         image = "gcr.io/${var.project_id}/nba-scraper-events:latest"
#         
#         env {
#           name  = "PROJECT_ID"
#           value = var.project_id
#         }
#         
#         env {
#           name = "ODDS_API_KEY"
#           value_from {
#             secret_key_ref {
#               name = google_secret_manager_secret.odds_api_key.secret_id
#               key  = "latest"
#             }
#           }
#         }
# 
#         resources {
#           limits = {
#             cpu    = "1"
#             memory = "1Gi"
#           }
#         }
#       }
#     }
# 
#     metadata {
#       annotations = {
#         "autoscaling.knative.dev/maxScale"      = "10"
#         "run.googleapis.com/execution-environment" = "gen2"
#       }
#     }
#   }
# 
#   traffic {
#     percent         = 100
#     latest_revision = true
#   }
# }
# 
# resource "google_cloud_run_service" "nba_scraper_odds" {
#   name     = "nba-scraper-odds"
#   location = var.region
#   project  = var.project_id
# 
#   template {
#     spec {
#       service_account_name = google_service_account.workflow_sa.email  # Using workflow_sa
#       
#       containers {
#         image = "gcr.io/${var.project_id}/nba-scraper-odds:latest"
#         
#         env {
#           name  = "PROJECT_ID"
#           value = var.project_id
#         }
#         
#         env {
#           name = "ODDS_API_KEY"
#           value_from {
#             secret_key_ref {
#               name = google_secret_manager_secret.odds_api_key.secret_id
#               key  = "latest"
#             }
#           }
#         }
# 
#         resources {
#           limits = {
#             cpu    = "1"
#             memory = "1Gi"
#           }
#         }
#       }
#     }
#   }
# 
#   traffic {
#     percent         = 100
#     latest_revision = true
#   }
# }

# ----------------------------------------------------------------------------
# Workflows - COMMENTED OUT
# ----------------------------------------------------------------------------
# 
# Uncomment after creating: workflows/nba_scraper_cloud_run.yaml
# 
# To create placeholder file:
#   mkdir -p workflows
#   echo 'main:\n  steps:\n    - init:\n        return: "Placeholder"' > workflows/nba_scraper_cloud_run.yaml
# 
# ----------------------------------------------------------------------------

# resource "google_workflows_workflow" "nba_scraper_workflow" {
#   name            = "nba-scraper-workflow"
#   region          = var.region
#   project         = var.project_id
#   service_account = google_service_account.workflow_sa.email
#   source_contents = file("${path.module}/../workflows/nba_scraper_cloud_run.yaml")
# 
#   labels = {
#     phase = "phase1"
#   }
# }

# ----------------------------------------------------------------------------
# IAM Permissions - COMMENTED OUT
# ----------------------------------------------------------------------------
# 
# Uncomment when enabling Cloud Run services
# 
# ----------------------------------------------------------------------------

# resource "google_secret_manager_secret_iam_member" "odds_api_key_access" {
#   secret_id = google_secret_manager_secret.odds_api_key.secret_id
#   role      = "roles/secretmanager.secretAccessor"
#   member    = "serviceAccount:${google_service_account.workflow_sa.email}"
#   project   = var.project_id
# }

# ----------------------------------------------------------------------------
# Cloud Build Trigger - COMMENTED OUT
# ----------------------------------------------------------------------------
# 
# Optional: Automated builds on Git push
# Configure after setting up GitHub integration
# 
# ----------------------------------------------------------------------------

# resource "google_cloudbuild_trigger" "nba_scrapers" {
#   name     = "nba-scrapers-deploy"
#   project  = var.project_id
#   location = var.region
# 
#   github {
#     owner = "your-github-username"  # UPDATE THIS
#     name  = "your-repo-name"        # UPDATE THIS
#     
#     push {
#       branch = "^main$"
#     }
#   }
# 
#   filename = "cloudbuild.yaml"
# }

# ----------------------------------------------------------------------------
# Outputs
# ----------------------------------------------------------------------------

output "odds_api_secret_id" {
  description = "Secret Manager secret ID for Odds API key"
  value       = google_secret_manager_secret.odds_api_key.secret_id
}

# output "scraper_events_url" {
#   description = "URL of nba-scraper-events service"
#   value       = google_cloud_run_service.nba_scraper_events.status[0].url
# }
# 
# output "scraper_odds_url" {
#   description = "URL of nba-scraper-odds service"
#   value       = google_cloud_run_service.nba_scraper_odds.status[0].url
# }