"""
Centralized resilience constants for the NBA Stats Scraper system.

This module provides a single source of truth for all resilience-related
configuration values including circuit breakers, retry limits, and timeouts.

Usage:
    from shared.constants.resilience import (
        CIRCUIT_BREAKER_THRESHOLD,
        CIRCUIT_BREAKER_TIMEOUT_MINUTES,
        HTTP_MAX_RETRIES,
    )

Created: 2026-01-24
Purpose: Consolidate hardcoded values from 5+ files into one location
"""

from datetime import timedelta


# =============================================================================
# CIRCUIT BREAKER CONFIGURATION
# =============================================================================
# Circuit breaker pattern prevents cascading failures by temporarily
# stopping requests to failing services.

# Number of consecutive failures before opening the circuit
CIRCUIT_BREAKER_THRESHOLD = 5

# How long the circuit stays open before attempting to close (minutes)
CIRCUIT_BREAKER_TIMEOUT_MINUTES = 30

# Pre-computed timedelta for convenience
CIRCUIT_BREAKER_TIMEOUT = timedelta(minutes=CIRCUIT_BREAKER_TIMEOUT_MINUTES)


# =============================================================================
# RETRY CONFIGURATION
# =============================================================================
# Maximum retry attempts for various operations

# HTTP request retries (scrapers, API calls)
HTTP_MAX_RETRIES = 3

# BigQuery DML operation retries
DML_MAX_RETRIES = 3

# Rate-limited API retries (higher limit for rate limiting)
RATE_LIMIT_MAX_RETRIES = 10

# Pub/Sub publish retries
PUBSUB_MAX_RETRIES = 3


# =============================================================================
# FAILURE THRESHOLDS
# =============================================================================
# Thresholds for triggering alerts or fallback behavior

# Entity-level failure threshold (e.g., player lookup failures)
ENTITY_FAILURE_THRESHOLD = 5

# Processor-level failure threshold
PROCESSOR_FAILURE_THRESHOLD = 5

# Name resolution consecutive failure threshold
NAME_RESOLUTION_FAILURE_THRESHOLD = 5


# =============================================================================
# PAGINATION GUARDS
# =============================================================================
# Maximum pages to prevent infinite loops in pagination

# Default max pages for API pagination
DEFAULT_MAX_PAGES = 1000

# BettingPros scraper pagination limit
BETTINGPROS_MAX_PAGES = 500

# BigDataBall / Google Drive pagination limit
BIGDATABALL_MAX_PAGES = 1000

# Ball Don't Lie API pagination limit
BDL_MAX_PAGES = 100


# =============================================================================
# TIMEOUT CONFIGURATION
# =============================================================================
# Various timeout values in seconds

# Default HTTP request timeout
HTTP_TIMEOUT_SECONDS = 30

# BigQuery query timeout
BIGQUERY_TIMEOUT_SECONDS = 120

# Thread pool future timeout multiplier
# (actual timeout = base_timeout * multiplier)
THREAD_POOL_TIMEOUT_MULTIPLIER = 1.5
