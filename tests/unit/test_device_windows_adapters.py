from mllminal.device.windows_adapters import FakeWindowsAdapter, WindowsProcessAdapter


def test_fake_windows_adapter_emits_metadata_only_process_window_file_and_idle_events() -> None:
    adapter = FakeWindowsAdapter(
        "windows.fake",
        [
            ("process", {"started": ["EXCEL.EXE"], "exited": ["OLD.EXE"]}),
            ("foreground", {"process_name": "EXCEL.EXE", "title": "secret budget"}),
            ("filesystem", {"event_type": "file.renamed", "path": "C:/Reports/a.xlsx"}),
            ("idle", {"idle": True}),
        ],
    )
    events = adapter.poll()
    assert [event.event_type for event in events] == [
        "application.started",
        "application.exited",
        "application.focused",
        "window.title_changed",
        "file.renamed",
        "user.idle",
    ]
    assert "secret budget" not in events[3].model_dump_json()


def test_missing_windows_dependency_degrades_without_failure() -> None:
    adapter = WindowsProcessAdapter(psutil_module=None)
    assert adapter.capability().available is False
    assert adapter.poll() == []
