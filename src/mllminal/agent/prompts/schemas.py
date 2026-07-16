"""Prompt-visible structured envelope schema, version 1."""

RESPONSE_ENVELOPE_SCHEMA = {
    "type": "object",
    "required": ["response", "plan"],
    "additionalProperties": False,
}
