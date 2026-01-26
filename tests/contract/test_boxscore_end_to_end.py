import json
from pathlib import Path

import pytest

from scrapers.espn.espn_game_boxscore import GetEspnBoxscore


FIXTURE_DIR = Path(__file__).parent / "fixtures"
HTML_FILE   = FIXTURE_DIR / "401766123.html"
EXPECTED    = FIXTURE_DIR / "401766123_expected.json"


@pytest.mark.skip(reason="""
Fixture files are empty - need to populate with real ESPN boxscore data.

To populate these fixtures:
1. Use the capture tool: python tools/fixtures/capture.py espn_game_boxscore --game_id 401766123
2. Save the HTML response to tests/contract/fixtures/401766123.html
3. Run the scraper on that HTML to generate the expected JSON output
4. Save the JSON to tests/contract/fixtures/401766123_expected.json
5. Remove this skip decorator

Note: Ensure you have permission to use ESPN data for testing purposes.
""")
def test_full_pipeline_matches_expected(monkeypatch):
    # 1) Load fixture HTML (pretend it was downloaded)
    html = HTML_FILE.read_text(encoding="utf‑8")

    # 2) Monkey‑patch scraper internals so we skip network & codecs
    scraper = GetEspnBoxscore()
    scraper.decoded_data = html
    scraper.opts = {"game_id": "401766123", "gamedate": "2025-01-01", "group": "test", "skipJson": "0"}

    # 3) Run only transform() → avoids touching ScraperBase download
    scraper.transform_data()

    # 4) Compare (ignore timestamp which is always now)
    got = scraper.data.copy()
    got.pop("timestamp", None)

    want = json.loads(EXPECTED.read_text(encoding="utf‑8"))
    assert got == want
