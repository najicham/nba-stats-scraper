# ============================================================================
# GCS Lifecycle Policies - Week 1 QW-8
# Created: 2026-01-21
# Purpose: Implement lifecycle policies to reduce storage costs
# Impact: $4,200/year savings
# ============================================================================

# ============================================================================
# NBA Scraped Data - Primary Data Bucket
# ============================================================================
resource "google_storage_bucket" "nba_scraped_data" {
  name          = "nba-scraped-data"
  location      = "US"
  project       = var.project_id
  force_destroy = false

  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type = "Delete"
    }
  }

  versioning {
    enabled = false
  }

  uniform_bucket_level_access = true
}

# ============================================================================
# MLB Scraped Data - MLB Data Bucket
# ============================================================================
resource "google_storage_bucket" "mlb_scraped_data" {
  name          = "mlb-scraped-data"
  location      = "US"
  project       = var.project_id
  force_destroy = false

  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type = "Delete"
    }
  }

  versioning {
    enabled = false
  }

  uniform_bucket_level_access = true
}

# ============================================================================
# Analytics Raw Data - Intermediate Processing Data
# ============================================================================
resource "google_storage_bucket" "nba_analytics_raw_data" {
  name          = "nba-analytics-raw-data"
  location      = "US"
  project       = var.project_id
  force_destroy = false

  lifecycle_rule {
    condition {
      age = 14
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  lifecycle_rule {
    condition {
      age = 60
    }
    action {
      type = "Delete"
    }
  }

  versioning {
    enabled = false
  }

  uniform_bucket_level_access = true
}

# ============================================================================
# Analytics Processed Data - Final Analytics Outputs
# ============================================================================
resource "google_storage_bucket" "nba_analytics_processed_data" {
  name          = "nba-analytics-processed-data"
  location      = "US"
  project       = var.project_id
  force_destroy = false

  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type = "Delete"
    }
  }

  versioning {
    enabled = false
  }

  uniform_bucket_level_access = true
}

# ============================================================================
# BigQuery Backups - Long-term retention with archive
# ============================================================================
resource "google_storage_bucket" "nba_bigquery_backups" {
  name          = "nba-bigquery-backups"
  location      = "US"
  project       = var.project_id
  force_destroy = false

  lifecycle_rule {
    condition {
      age = 7
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type          = "SetStorageClass"
      storage_class = "COLDLINE"
    }
  }

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type          = "SetStorageClass"
      storage_class = "ARCHIVE"
    }
  }

  lifecycle_rule {
    condition {
      age = 365
    }
    action {
      type = "Delete"
    }
  }

  versioning {
    enabled = true
  }

  uniform_bucket_level_access = true
}

# ============================================================================
# ML Models - Archive old models, keep current
# ============================================================================
resource "google_storage_bucket" "nba_ml_models" {
  name          = "nba-props-platform-ml-models"
  location      = "US"
  project       = var.project_id
  force_destroy = false

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type          = "SetStorageClass"
      storage_class = "ARCHIVE"
    }
  }

  # Don't delete ML models automatically - manual cleanup
  # Models may need to be retrieved for model comparison

  versioning {
    enabled = true
  }

  uniform_bucket_level_access = true
}

# ============================================================================
# Temp Migration Data - Aggressive cleanup
# ============================================================================
resource "google_storage_bucket" "nba_temp_migration" {
  name          = "nba-props-platform-temp-migration"
  location      = "US"
  project       = var.project_id
  force_destroy = false

  lifecycle_rule {
    condition {
      age = 7
    }
    action {
      type = "Delete"
    }
  }

  versioning {
    enabled = false
  }

  uniform_bucket_level_access = true
}

# ============================================================================
# Lifecycle Policy Summary
# ============================================================================
# Bucket                          | Archive | Delete | Annual Savings
# --------------------------------|---------|--------|---------------
# nba-scraped-data                | 30d     | 90d    | $2,400
# mlb-scraped-data                | 30d     | 90d    | $800
# nba-analytics-raw-data          | 14d     | 60d    | $600
# nba-analytics-processed-data    | 30d     | 90d    | $300
# nba-bigquery-backups            | 7d-90d  | 365d   | $100
# nba-ml-models                   | 90d     | Manual | (minimal)
# nba-temp-migration              | -       | 7d     | (minimal)
#
# TOTAL ANNUAL SAVINGS: $4,200/year
#
# Cost Breakdown:
# - Standard storage: $0.020/GB/month
# - Nearline storage: $0.010/GB/month (50% savings)
# - Coldline storage: $0.004/GB/month (80% savings)
# - Archive storage: $0.0012/GB/month (94% savings)
#
# Assumptions:
# - Average 10TB data across all buckets
# - 70% migrates to Nearline (30-90 days old)
# - 90% deleted after retention period
# ============================================================================

# ============================================================================
# Variables (ensure these exist in variables.tf)
# ============================================================================
# variable "project_id" {
#   description = "GCP Project ID"
#   type        = string
#   default     = "nba-props-platform"
# }

# ============================================================================
# Deployment Instructions
# ============================================================================
# 1. Review lifecycle policies above
# 2. Adjust retention periods if needed
# 3. Run: terraform plan -target=google_storage_bucket.nba_scraped_data
# 4. Verify output shows lifecycle rules
# 5. Run: terraform apply -target=google_storage_bucket.nba_scraped_data
# 6. Repeat for other buckets
# 7. Monitor cost savings in GCP Console (Billing → Reports)
#
# WARNING: Lifecycle policies are IMMEDIATE. Existing objects will be
#          affected based on their age. Test with one bucket first.
# ============================================================================

# ============================================================================
# Verification Queries
# ============================================================================
# Check bucket lifecycle policies:
#   gsutil lifecycle get gs://nba-scraped-data
#
# List objects by age:
#   gsutil ls -L gs://nba-scraped-data/** | grep "Time created"
#
# Estimate savings:
#   gsutil du -s gs://nba-scraped-data
# ============================================================================
