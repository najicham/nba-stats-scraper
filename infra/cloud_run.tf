# infra/cloud_run.tf
# Add this to your existing Terraform infrastructure

# Cloud Run services for scrapers
resource "google_cloud_run_service" "nba_scraper_events" {
  name     = "nba-scraper-events"
  location = var.region

  template {
    spec {
      service_account_name = google_service_account.nba_scraper.email
      
      containers {
        image = "gcr.io/${var.project_id}/nba-scraper-events:latest"
        
        env {
          name  = "PROJECT_ID"
          value = var.project_id
        }
        
        env {
          name = "ODDS_API_KEY"
          value_from {
            secret_key_ref {
              name = google_secret_manager_secret.odds_api_key.secret_id
              key  = "latest"
            }
          }
        }

        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }
      }
    }

    metadata {
      annotations = {
        "autoscaling.knative.dev/maxScale" = "10"
        "run.googleapis.com/execution-environment" = "gen2"
      }
    }
  }

  traffic {
    percent         = 100
    latest_revision = true
  }
}

resource "google_cloud_run_service" "nba_scraper_odds" {
  name     = "nba-scraper-odds"
  location = var.region

  template {
    spec {
      service_account_name = google_service_account.nba_scraper.email
      
      containers {
        image = "gcr.io/${var.project_id}/nba-scraper-odds:latest"
        
        env {
          name  = "PROJECT_ID"
          value = var.project_id
        }
        
        env {
          name = "ODDS_API_KEY"
          value_from {
            secret_key_ref {
              name = google_secret_manager_secret.odds_api_key.secret_id
              key  = "latest"
            }
          }
        }

        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }
      }
    }
  }

  traffic {
    percent         = 100
    latest_revision = true
  }
}

# Secret Manager for API key
resource "google_secret_manager_secret" "odds_api_key" {
  secret_id = "odds-api-key"
  
  replication {
    automatic = true
  }
}

# Workflows
resource "google_workflows_workflow" "nba_scraper_workflow" {
  name            = "nba-scraper-workflow"
  region          = var.region
  service_account = google_service_account.nba_scraper.email
  source_contents = file("${path.module}/../workflows/nba_scraper_cloud_run.yaml")
}

# IAM for Cloud Run to access secrets
resource "google_secret_manager_secret_iam_member" "odds_api_key_access" {
  secret_id = google_secret_manager_secret.odds_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.nba_scraper.email}"
}

# Cloud Build trigger (optional - for automated builds)
resource "google_cloudbuild_trigger" "nba_scrapers" {
  name = "nba-scrapers-deploy"

  github {
    owner = "your-github-username"  # UPDATE THIS
    name  = "your-repo-name"        # UPDATE THIS
    
    push {
      branch = "^main$"
    }
  }

  filename = "cloudbuild.yaml"
}
