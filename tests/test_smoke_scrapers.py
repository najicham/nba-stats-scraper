import pytest
import os
import json
import subprocess

# If you want to automatically load .env, uncomment these lines:
from dotenv import load_dotenv
load_dotenv()  # ensures ODDS_API_KEY is loaded from your .env if present

@pytest.mark.parametrize("module_name,cli_args,output_file,allow_empty", [
    # 1) Example: nbac_game_score
    (
        "nbac_game_score",
        ["--gamedate", "2023-04-02", "--group", "test"],
        "/tmp/getnbacomgamescore.json",
        False  # we typically expect some scoreboard data, but adjust as needed
    ),

    # 2) Example: oddsa_events
    (
        "oddsa_events",
        [
            "--sport", "basketball_nba",
            "--api_key", os.environ["ODDS_API_KEY"],  # KeyError if not set
            "--group", "test"
        ],
        "/tmp/oddsapi_events.json",
        True  # allow_empty=True in case no upcoming events
    ),

    (
        "oddsa_events_his",  # must match scrapers/odds_api_historical_events.py
        [
            "--api_key", os.environ["ODDS_API_KEY"],     # Use your real key
            "--sport", "basketball_nba",
            "--date", "2025-05-10T00:00:00Z",           # Something in the future
            "--group", "test"
        ],
        "/tmp/oddsapi_historical_events.json",
        True  # historical might return empty, so let's allow_empty
    ),
])
def test_scraper_smoke(module_name, cli_args, output_file, allow_empty):
    """
    Basic smoke test for scrapers using '-m' module execution:
      1) Runs the scraper with minimal required CLI args
      2) Checks it exits without error
      3) Verifies an output file is created (and not empty in terms of bytes)
      4) If we expect valid JSON, parse it. If allow_empty=False, we assert non-empty JSON.

    If any assertion fails, we print STDOUT/STDERR from the subprocess to aid debugging.
    """

    # Remove any leftover file from previous runs
    if os.path.exists(output_file):
        os.remove(output_file)

    # Build the command to run the scraper as a module
    cmd = ["python", "-m", f"scrapers.{module_name}"] + cli_args
    print(f"Running command: {cmd}")

    # Run the scraper in a subprocess
    proc = subprocess.run(cmd, capture_output=True, text=True)

    # Helper function to display logs if we fail an assertion
    def show_logs_and_fail(message):
        # Print logs for debugging
        print("\n========== DEBUG LOGS (Scraper) ==========")
        print("STDOUT:\n", proc.stdout or "<no stdout>")
        print("STDERR:\n", proc.stderr or "<no stderr>")
        print("==========================================\n")
        pytest.fail(message)

    # 1) Check that the scraper didn't crash (returncode=0)
    if proc.returncode != 0:
        show_logs_and_fail(
            f"Module '{module_name}' failed with return code {proc.returncode}."
        )

    # 2) Verify the output file is created
    if not os.path.exists(output_file):
        show_logs_and_fail(f"No output file found at {output_file}")

    # 3) Check it's not empty in terms of bytes
    size = os.path.getsize(output_file)
    if size == 0:
        show_logs_and_fail(f"Output file is empty: {output_file}")

    # 4) If we expect JSON, parse it. If allow_empty=False, we assert it's non-empty.
    parse_json_modules = ["nbac_game_score", "oddsa_events"]
    if module_name in parse_json_modules:
        try:
            with open(output_file, "r") as f:
                data = json.load(f)
            if not allow_empty and not data:
                show_logs_and_fail("JSON parsed but is empty (allow_empty=False).")
            else:
                print(
                    f"Found {len(data) if isinstance(data, list) else 'N/A'} records. "
                    "Empty is allowed." if allow_empty else ""
                )
        except json.JSONDecodeError:
            print("Output is raw/invalid JSON, which may be expected for some scrapers.")
