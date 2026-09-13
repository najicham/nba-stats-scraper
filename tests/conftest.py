# tests/conftest.py
import sys
import os

# Add project root to path for imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import gzip, json, pathlib, pytest

SAMPLES = pathlib.Path(__file__).parent / "samples"

def load(folder: str, filename: str, binary: bool = False):
    """
    Read a fixture from tests/samples/, transparently handling .gz files.
    Set binary=True to return bytes, else str.
    """
    fp = SAMPLES / folder / filename
    if fp.suffix == ".gz":
        with gzip.open(fp, "rb") as f:
            data = f.read()
            return data if binary else data.decode("utf‑8")
    mode = "rb" if binary else "r"
    with open(fp, mode) as f:
        return f.read()


def install_anonymous_credentials(monkeypatch, project: str = 'nba-props-platform'):
    """Force Application Default Credentials to resolve to anonymous, always.

    Two separate problems, one fix (2026-09-08):

    1. On CI there are no credentials, so any test that constructs a real
       `bigquery.Client()` / `storage.Client()` — directly, or indirectly inside
       the code under test — dies with `DefaultCredentialsError`. That was 93 of
       the 171 unit-test failures, plus a handful more where the code under test
       swallows the error and the test then fails on a confusing downstream
       assertion (`_run_start_time` missing, `assert False`).

    2. On a developer machine ADC *is* present, so those same tests quietly ran
       real GCP work against the owner's project every time anyone ran the
       suite. `tests/unit/patterns/test_dependency_tracking.py` failed 22/22
       without ADC but only 2/22 with it — the 20-test difference was live
       BigQuery, billed to a human, from a unit-test run.

    Anonymous credentials let client construction succeed offline while making
    any *actual* request fail loudly with a 401 rather than succeeding for real.
    Tests that want a mock client still patch it themselves; this only removes
    the credential lookup from the path.

    Call this from an autouse fixture in a directory-level conftest. It is NOT
    applied globally, because tests/integration/ legitimately wants real ADC.
    """
    try:
        import google.auth
        from google.auth import credentials as ga_credentials
    except ImportError:  # google libs absent — nothing to stub
        return

    anonymous = ga_credentials.AnonymousCredentials()

    monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', project)
    monkeypatch.setenv('GCLOUD_PROJECT', project)
    monkeypatch.setattr(google.auth, 'default', lambda *a, **k: (anonymous, project))
    monkeypatch.setattr(
        'google.auth._default.default',
        lambda *a, **k: (anonymous, project),
        raising=False,
    )
