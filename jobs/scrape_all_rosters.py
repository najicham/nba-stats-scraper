import time
from config.nba_teams import NBA_TEAMS
from scrapers.nbac_roster import GetNbaTeamRoster

for team in NBA_TEAMS:
    opts = {
        "teamAbbr": team["abbr"],
        "group": "prod"  # or "test" if running locally
    }

    print(f"Scraping roster for {team['abbr']}...")
    try:
        scraper = GetNbaTeamRoster()
        result = scraper.run(opts)
        print(f"✅ Completed {team['abbr']}, result: {result}")
    except Exception as e:
        print(f"❌ Error scraping {team['abbr']}: {e}")

    time.sleep(1)  # polite delay between requests to avoid hammering NBA.com

print("✅ All rosters scraped.")
