"""Claude client wrapper — PHI-safe by construction.

Every prompt is de-identified and checked (fail-closed) before it is sent. The
CARC classifier tie-break uses the small, cheap model (Haiku); drafting (Phase 1)
uses the large model (Opus). Prompt bodies are never logged — only a prompt hash
is retained (in the audit log).

Phase 0 triage is deterministic; this classifier is only a tie-break for an
ambiguous/unmapped CARC. It is optional: absent an API key it raises a clear
error rather than degrading silently.
"""

from __future__ import annotations

import hashlib
import json

from rcm.core.config import get_settings
from rcm.enums import TriageClass
from rcm.llm.deident import assert_deidentified, deidentify

_TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "triage_class": {
            "type": "string",
            "enum": [c.value for c in TriageClass],
        }
    },
    "required": ["triage_class"],
    "additionalProperties": False,
}


def prompt_hash(prompt: str) -> str:
    """Stable hash of a prompt for the audit log (we never store the body)."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


class ClaudeClassifier:
    """Thin wrapper around Anthropic Messages for CARC tie-breaking."""

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set; CARC classifier is unavailable. "
                "Phase 0 triage is deterministic and does not require it."
            )
        # Imported lazily so the package works without the SDK installed offline.
        import anthropic

        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.classifier_model

    def classify(self, denial_description: str, names: tuple[str, ...] = ()) -> TriageClass:
        """Classify an ambiguous denial. Input is de-identified before sending."""
        safe = deidentify(denial_description, names=names)
        assert_deidentified(safe)  # fail-closed: never send residual PHI

        prompt = (
            "You are a medical billing triage assistant. Classify this denial into "
            "exactly one class. Output only the structured result.\n\n"
            f"Denial: {safe}"
        )
        response = self._client.messages.create(
            model=self._model,
            max_tokens=256,
            output_config={"format": {"type": "json_schema", "schema": _TRIAGE_SCHEMA}},
            messages=[{"role": "user", "content": prompt}],
        )
        text = next(b.text for b in response.content if b.type == "text")
        return TriageClass(json.loads(text)["triage_class"])
