from datetime import UTC, datetime, timedelta
from pathlib import Path

from mllminal.agent.response_cache import ResponseCache, response_cache_key


def _key(content: str) -> str:
    return response_cache_key(
        provider="qwen",
        model="qwen3:4b",
        workspace_root="C:/workspace",
        content=content,
    )


def test_response_cache_survives_a_new_store_instance(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    cache = ResponseCache(database, ttl_seconds=60, max_entries=4)
    key = _key("hi")

    assert cache.get(key) is None
    cache.put(key, "Hello from Mil.")

    assert ResponseCache(database, ttl_seconds=60, max_entries=4).get(key) == "Hello from Mil."


def test_response_cache_expires_entries(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    now = [datetime(2026, 8, 24, tzinfo=UTC)]
    cache = ResponseCache(database, ttl_seconds=30, max_entries=4, clock=lambda: now[0])
    key = _key("hello")
    cache.put(key, "Hi.")

    now[0] += timedelta(seconds=31)

    assert cache.get(key) is None


def test_response_cache_prunes_least_recently_used_entries(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    now = [datetime(2026, 8, 24, tzinfo=UTC)]
    cache = ResponseCache(database, ttl_seconds=300, max_entries=2, clock=lambda: now[0])
    first, second, third = (_key(value) for value in ("one", "two", "three"))

    cache.put(first, "1")
    now[0] += timedelta(seconds=1)
    cache.put(second, "2")
    assert cache.get(first) == "1"
    now[0] += timedelta(seconds=1)
    cache.put(third, "3")

    assert cache.get(first) == "1"
    assert cache.get(second) is None
    assert cache.get(third) == "3"


def test_response_cache_key_separates_provider_model_workspace_and_content() -> None:
    baseline = _key("hi")

    assert baseline != response_cache_key(
        provider="deterministic",
        model="fixture",
        workspace_root="C:/workspace",
        content="hi",
    )
    assert baseline != response_cache_key(
        provider="qwen",
        model="qwen3:4b",
        workspace_root="C:/other",
        content="hi",
    )
    assert baseline != _key("hello")
