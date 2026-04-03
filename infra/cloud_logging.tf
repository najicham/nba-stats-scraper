# Cloud Logging exclusion filters
# Reduces logging costs by filtering high-volume, low-value log entries.
# Session 509: Added to bring 186 GB/month logging toward 50 GB free tier.
#
# IMPORTANT: Always manage exclusions here, NOT in GCP Console.
# Console-only changes are wiped on next terraform apply.

resource "google_logging_project_exclusion" "exclude_health_checks" {
  name        = "exclude-health-checks"
  description = "Exclude /health, /healthz, /ready GET logs from Cloud Run (health checks every 30s = millions/month)"
  filter      = <<-EOT
    resource.type="cloud_run_revision"
    AND (textPayload=~".*GET /health.*"
      OR textPayload=~".*GET /healthz.*"
      OR textPayload=~".*GET /ready.*")
  EOT
  disabled = false
}

resource "google_logging_project_exclusion" "exclude_heartbeats" {
  name        = "exclude-heartbeats"
  description = "Exclude repetitive heartbeat logs from Phase 2/3/4 processors (sent every 60s)"
  filter      = <<-EOT
    resource.type="cloud_run_revision"
    AND jsonPayload.message="Heartbeat"
  EOT
  disabled = false
}
