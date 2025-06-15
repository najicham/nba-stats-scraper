import json
from pathlib import Path

from scrapers.espn.espn_game_boxscore import GetEspnBoxscore


FIXTURE_DIR = Path(__file__).parent / "fixtures"
HTML_FILE   = FIXTURE_DIR / "401766123.html"
EXPECTED    = FIXTURE_DIR / "401766123_expected.json"


def test_full_pipeline_matches_expected(monkeypatch):
    # 1) Load fixture HTML (pretend it was downloaded)
    html = HTML_FILE.read_text(encoding="utf‑8")

    # 2) Monkey‑patch scraper internals so we skip network & codecs
    scraper = GetEspnBoxscore()
    scraper.decoded_data = html
    scraper.opts = {"gameId": "401766123", "group": "test", "skipJson": "0"}

    # 3) Run only transform() → avoids touching ScraperBase download
    scraper.transform_data()

    # 4) Compare (ignore timestamp which is always now)
    got = scraper.data.copy()
    got.pop("timestamp", None)

    want = json.loads(EXPECTED.read_text(encoding="utf‑8"))
    assert got == want
