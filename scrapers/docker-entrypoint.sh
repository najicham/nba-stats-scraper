#!/bin/bash
# scrapers/docker-entrypoint.sh
# Entry point for NBA Scrapers service

set -e

# Default environment
export PORT=${PORT:-8080}
export PYTHONPATH="/app:/app/shared"

echo "Starting NBA Scrapers service..."
echo "PORT: $PORT"
echo "PYTHONPATH: $PYTHONPATH"

# Simple routing based on arguments
case "${1:-serve}" in
    "--events" | "events")
        echo "Starting Events scraper service"
        exec python -m scrapers.oddsapi.oddsa_events_his --serve
        ;;
    "--props" | "props")
        echo "Starting Player Props scraper service"  
        exec python -m scrapers.oddsapi.oddsa_player_props_his --serve
        ;;
    "--serve" | "serve" | "")
        # Default: start events scraper (can be changed)
        echo "Starting default Events scraper service"
        exec python -m scrapers.oddsapi.oddsa_events_his --serve
        ;;
    *)
        echo "Unknown command: $1"
        echo "Usage: $0 [--events|--props|--serve]"
        exit 1
        ;;
esac