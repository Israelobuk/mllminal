from mllminal.contracts import ProviderResponseMetadata
from mllminal.runtime_store import RuntimeStore


def test_provider_metadata_is_persisted_without_response_content(tmp_path) -> None:
    store = RuntimeStore(tmp_path / "state.db")
    store.initialize()
    session = store.create_session(str(tmp_path))
    task = store.create_task(session.id, "Inspect", "Inspect safely")
    metadata = ProviderResponseMetadata(
        task_id=task.id,
        provider="qwen",
        model="qwen:test",
        prompt_version="v1",
        completion_status="completed",
        validation_succeeded=True,
        retry_count=1,
        input_tokens=12,
        output_tokens=7,
    )

    saved = store.save_provider_metadata(metadata)

    assert store.get_provider_metadata(task.id) == saved
    assert "response" not in saved.model_dump()
