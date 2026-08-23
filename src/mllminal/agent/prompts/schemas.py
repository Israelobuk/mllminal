"""Prompt-visible structured envelope schema, version 1."""

RESPONSE_ENVELOPE_SCHEMA = {
    "type": "object",
    "required": ["response", "plan"],
    "additionalProperties": False,
    "properties": {
        "response": {"type": "string"},
        "plan": {
            "type": "object",
            "required": ["title", "steps"],
            "additionalProperties": False,
            "properties": {
                "title": {"type": "string"},
                "steps": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["step_id", "description", "tool"],
                        "additionalProperties": False,
                        "properties": {
                            "step_id": {"type": "string"},
                            "description": {"type": "string"},
                            "tool": {
                                "type": "object",
                                "required": ["name", "arguments"],
                                "additionalProperties": False,
                                "properties": {
                                    "name": {"type": "string"},
                                    "arguments": {"type": "object"},
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}
