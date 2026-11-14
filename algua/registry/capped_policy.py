"""Data-independent reconstruction of signed live provider policy."""

from __future__ import annotations

import hashlib

from algua.config.settings import get_settings
from algua.contracts.canonical import canonical_json


def provider_policy() -> dict:
    settings = get_settings()
    if not settings.bars_refresh_provider_live:
        raise ValueError("live bars provider must be explicitly configured")
    return {
        "provider": settings.bars_refresh_provider_live,
        "alpaca_data_url": settings.alpaca_data_url,
        "exchange": settings.exchange,
    }


def context_digest(value: dict) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()
