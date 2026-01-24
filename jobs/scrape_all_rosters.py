"""
Job script to scrape all NBA team rosters.

Usage: python jobs/scrape_all_rosters.py
"""
import logging
import time

from config.nba_teams import NBA_TEAMS
from scrapers.nbacom.nbac_roster import GetNbaTeamRoster

# Configure logging for this job
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

for team in NBA_TEAMS:
    opts = {
        "teamAbbr": team["abbr"],
        "group": "prod"  # or "test" if running locally
    }

    logger.info(f"Scraping roster for {team['abbr']}...")
    try:
        scraper = GetNbaTeamRoster()
        result = scraper.run(opts)
        logger.info(f"Completed {team['abbr']}, result: {result}")
    except Exception as e:
        logger.error(f"Error scraping {team['abbr']}: {e}")

    time.sleep(1)  # polite delay between requests to avoid hammering NBA.com

logger.info("All rosters scraped.")
