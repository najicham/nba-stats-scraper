#!/bin/bash
set -e

# Clone the repo to get git context
echo "Cloning repository for git context..."
git clone --depth=50 https://github.com/najiabdel/nba-stats-scraper.git /tmp/repo
cd /tmp/repo

# Run the drift alerter from the repo context
python3 bin/monitoring/deployment_drift_alerter.py
