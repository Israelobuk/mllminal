from mllminal.agent.prompts import PROMPT_VERSION, repair_message, system_message


def test_versioned_prompts_prohibit_direct_execution_and_support_repair() -> None:
    system = system_message()
    repair = repair_message("unknown tool: shell.run")

    assert PROMPT_VERSION == "v1"
    assert "cannot execute tools directly" in system
    assert "Every tool requires approval" in system
    assert "Return only a valid JSON envelope" in repair
    assert "shell.run" in repair
