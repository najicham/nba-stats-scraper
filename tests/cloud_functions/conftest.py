"""Shared configuration for Cloud Function handler tests.

These are unit tests of CF handlers and must not reach live GCP — several of
them construct BigQuery/Storage clients through the code under test. Without the
credential stub they fail with DefaultCredentialsError on CI and issue real
requests on a developer machine.

⚠️ This whole directory is NOT run by .github/workflows/test.yml, which only
collects tests/unit/. Nine tests in test_phase5_to_phase6_handler.py alone were
failing unnoticed as of 2026-09-08.
"""

import pytest


@pytest.fixture(autouse=True)
def _stub_google_credentials(monkeypatch):
    from tests.conftest import install_anonymous_credentials

    install_anonymous_credentials(monkeypatch)
    yield
