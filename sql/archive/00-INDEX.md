# SQL Scripts Archive

## Overview
This directory contains archived SQL scripts that are no longer actively used but kept for reference.

## Contents

### Data Initialization
- `nba_travel_distances_insert.sql` (September 2025)
  - One-time data load for NBA travel distance calculations
  - Used during initial system setup
  - Data now maintained through automated processes

## Usage

These scripts are **not** intended for regular use. They are archived because:
1. They were one-time operations (already executed)
2. The functionality is now handled by automated processes
3. The data is maintained through different means

## Active SQL Scripts

For current SQL scripts, see:
- **Validation queries:** `/validation/*.sql`
- **Schema definitions:** `/schemas/bigquery/`
- **Migration scripts:** `/migrations/` (if applicable)

## Retention Policy

SQL scripts are moved here when:
- The operation is complete and won't be repeated
- The script is superseded by automated processes
- The script is more than 90 days old and unused

**Retention:** Review annually, delete if no longer needed for reference

---
**Last Updated:** January 22, 2026
