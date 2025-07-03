# Infrastructure — NBA Player‑Prop Pipeline

This folder contains **all Terraform code** needed to create the
operational (“ops”) dataset and its tracking tables in BigQuery, along
with IAM bindings so Cloud Workflows, Cloud Run services, and analysts
can access them.

---

## File map

| File | Purpose |
|------|---------|
| **`versions.tf`** | Pins Terraform CLI (≥ 1.6) and the Google provider (`~> 5.30`) for reproducible builds. |
| **`provider.tf`** | Google provider config (`project`, `region`) and a small `local.ops_dataset` helper string. |
| **`variables.tf`** | Declares `project_id`, `region`, and `ops_dataset_id` variables. |
| **`terraform.tfvars`** *(or `dev.tfvars`)* | Supplies values for those variables. Rename to `terraform.tfvars` for auto‑loading, or load manually with `-var-file`. |
| **`dataset_ops.tf`** | Creates the **`ops`** BigQuery dataset in the chosen region. |
| **`tables_ops.tf`**  | Defines the four operational tables (partitioned & clustered). |
| **`iam_ops.tf`** | IAM bindings: grants specific service‑accounts `dataEditor` or `dataViewer` roles on the dataset. |
| **`outputs.tf`** | Prints handy console links to the dataset and tables after `terraform apply`. |

---

## The four ops tables

| Table | Partition | Cluster | What it stores |
|-------|-----------|---------|----------------|
| `scraper_runs` | `run_ts` (DAY) | `process_id` | One row per scraper **attempt** (STARTED, SUCCESS, FAILED). |
| `process_tracking` | `arrived_at` (DAY) | `process_id`, `entity_key` | Version handle for every successful ingest slice. |
| `player_report_runs` | `game_date` (DAY) | `player_id` | State machine + audit info for each *(player, game)* report. |
| `player_history_manifest` | `updated_at` (DAY) | `player_id` | “How far back is history loaded?” checkpoint per player. |

_All four live in the single region **`ops`** dataset, reducing latency and egress charges._

---

## Quick‑start (dev)

```bash
# 0) Authenticate to Google Cloud
gcloud auth application-default login

# 1) Initialise Terraform providers
cd infra
terraform init

# 2) Provide your project & region
#    Option A – auto‑load:
echo 'project_id = "my-dev-project"' > terraform.tfvars
echo 'region     = "us-west2"'      >> terraform.tfvars

#    Option B – explicit file:
# terraform apply -var-file="dev.tfvars"

# 3) Apply
terraform apply
