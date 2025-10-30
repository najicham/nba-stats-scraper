# ============================================================================
# Pub/Sub Topics and Subscriptions for NBA Props Platform
# Phase 4 Precompute Infrastructure
# ============================================================================
# 
# Deployment Strategy:
# 1. Create topics + PULL subscriptions first (this file)
# 2. Deploy precompute service
# 3. Update subscriptions to PUSH (see update script below)
# ============================================================================

locals {
  processor_sa_email = "processor-sa@${var.project_id}.iam.gserviceaccount.com"
}

# ----------------------------------------------------------------------------
# Phase 4 Topics
# ----------------------------------------------------------------------------

resource "google_pubsub_topic" "analytics_ready" {
  name    = "analytics-ready"
  project = var.project_id

  labels = {
    phase       = "phase3-to-phase4"
    environment = "production"
  }

  message_retention_duration = "86400s" # 24 hours
}

resource "google_pubsub_topic" "precompute_complete" {
  name    = "precompute-complete"
  project = var.project_id

  labels = {
    phase       = "phase4-to-phase5"
    environment = "production"
  }

  message_retention_duration = "86400s"
}

resource "google_pubsub_topic" "precompute_updated" {
  name    = "precompute-updated"
  project = var.project_id

  labels = {
    phase       = "phase4-to-phase5"
    environment = "production"
  }

  message_retention_duration = "86400s"
}

resource "google_pubsub_topic" "line_changed" {
  name    = "line-changed"
  project = var.project_id

  labels = {
    phase       = "phase5"
    environment = "production"
  }

  message_retention_duration = "3600s" # 1 hour (real-time)
}

# ----------------------------------------------------------------------------
# Dead Letter Queues
# ----------------------------------------------------------------------------

resource "google_pubsub_topic" "analytics_ready_dlq" {
  name    = "analytics-ready-dead-letter"
  project = var.project_id

  labels = {
    purpose = "dead-letter-queue"
    phase   = "phase4"
  }
}

resource "google_pubsub_topic" "line_changed_dlq" {
  name    = "line-changed-dead-letter"
  project = var.project_id

  labels = {
    purpose = "dead-letter-queue"
    phase   = "phase4"
  }
}

# ----------------------------------------------------------------------------
# PULL Subscriptions (will update to PUSH after service deployment)
# ----------------------------------------------------------------------------

resource "google_pubsub_subscription" "analytics_ready_precompute" {
  name    = "analytics-ready-precompute-sub"
  topic   = google_pubsub_topic.analytics_ready.name
  project = var.project_id

  ack_deadline_seconds       = 600
  message_retention_duration = "86400s"
  retain_acked_messages      = false

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.analytics_ready_dlq.id
    max_delivery_attempts = 5
  }

  labels = {
    subscriber = "precompute-service"
    phase      = "phase4"
    type       = "pull"  # Will update to push after service deployed
  }
}

resource "google_pubsub_subscription" "line_changed_precompute" {
  name    = "line-changed-precompute-sub"
  topic   = google_pubsub_topic.line_changed.name
  project = var.project_id

  ack_deadline_seconds       = 300
  message_retention_duration = "3600s"
  retain_acked_messages      = false

  retry_policy {
    minimum_backoff = "5s"
    maximum_backoff = "60s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.line_changed_dlq.id
    max_delivery_attempts = 3
  }

  labels = {
    subscriber = "precompute-service"
    phase      = "phase4"
    latency    = "real-time"
    type       = "pull"  # Will update to push after service deployed
  }
}

# ----------------------------------------------------------------------------
# IAM: Publishing Permissions
# ----------------------------------------------------------------------------

# Allow processor-sa to publish completion messages
resource "google_pubsub_topic_iam_member" "processor_sa_publish_precompute_complete" {
  project = var.project_id
  topic   = google_pubsub_topic.precompute_complete.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${local.processor_sa_email}"
}

resource "google_pubsub_topic_iam_member" "processor_sa_publish_precompute_updated" {
  project = var.project_id
  topic   = google_pubsub_topic.precompute_updated.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${local.processor_sa_email}"
}

# ----------------------------------------------------------------------------
# IAM: Subscription Permissions
# ----------------------------------------------------------------------------

resource "google_pubsub_subscription_iam_member" "processor_sa_subscribe_analytics_ready" {
  project      = var.project_id
  subscription = google_pubsub_subscription.analytics_ready_precompute.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${local.processor_sa_email}"
}

resource "google_pubsub_subscription_iam_member" "processor_sa_subscribe_line_changed" {
  project      = var.project_id
  subscription = google_pubsub_subscription.line_changed_precompute.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${local.processor_sa_email}"
}

# ----------------------------------------------------------------------------
# Outputs
# ----------------------------------------------------------------------------

output "pubsub_topics" {
  description = "Phase 4 Pub/Sub topics"
  value = {
    analytics_ready     = google_pubsub_topic.analytics_ready.name
    precompute_complete = google_pubsub_topic.precompute_complete.name
    precompute_updated  = google_pubsub_topic.precompute_updated.name
    line_changed        = google_pubsub_topic.line_changed.name
  }
}

output "pubsub_subscriptions" {
  description = "Phase 4 Pub/Sub subscriptions (PULL - update to PUSH after service deployed)"
  value = {
    analytics_ready = google_pubsub_subscription.analytics_ready_precompute.name
    line_changed    = google_pubsub_subscription.line_changed_precompute.name
  }
}

output "precompute_service_instructions" {
  description = "Instructions for updating subscriptions after service deployment"
  value       = "After deploying precompute service, run: bin/precompute/deploy/update_pubsub_to_push.sh"
}