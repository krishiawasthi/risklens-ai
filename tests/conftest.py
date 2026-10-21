"""Shared test setup.

Tests must not read your real .env file, so they give the same result on
every machine. RiskLens calls load_dotenv() inside its functions; this
replaces it with a version that does nothing, for every test.
"""
import pytest


@pytest.fixture(autouse=True)
def ignore_dotenv_file(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
