from mllminal.agent.latency import LatencyTrace


def test_latency_trace_reports_milestones_and_derived_durations() -> None:
    trace = LatencyTrace(
        route="chat",
        model="qwen3:4b",
        history_size=4,
        tool_count=0,
        warm=True,
    )
    trace.mark("input_received", 1.0)
    trace.mark("routing_complete", 1.1)
    trace.mark("context_ready", 1.3)
    trace.mark("ollama_request_started", 1.4)
    trace.mark("first_token_received", 2.0)
    trace.mark("response_complete", 2.5)

    result = trace.to_dict()

    assert result["route"] == "chat"
    assert result["model"] == "qwen3:4b"
    assert result["warm"] is True
    assert result["durations_ms"] == {
        "routing": 100.0,
        "context": 200.0,
        "ollama_wait": 600.0,
        "ttft": 1000.0,
        "generation": 500.0,
        "total": 1500.0,
    }
