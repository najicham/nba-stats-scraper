# Processors

Scripts for managing data processors that transform raw scraped data into structured database records.

## Structure
- `deploy/` - Deployment scripts for processor services
- `monitoring/` - Scripts to monitor processor job execution
- `validation/` - Scripts to validate processed data quality

## Process Flow
Raw JSON (GCS Buckets) → Processors → Structured Data (Database)
