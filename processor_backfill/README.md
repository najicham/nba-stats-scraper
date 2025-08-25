# Processor Backfill Jobs

This directory contains backfill jobs for processing scraped NBA data from GCS to BigQuery.

## Structure

Each processor has its own subdirectory with:
- `{processor_name}_backfill_job.py` - The actual job script
- `job-config.env` - Configuration for deployment and runtime

## Adding a New Processor

1. Create a new directory for your processor:
```bash
mkdir processor_backfill/my_new_processor