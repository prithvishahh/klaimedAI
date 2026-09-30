"""Chart-support check for diagnosis (ICD-10-CM) codes.

Guardrail Rule 3: an agent may only *add* an ICD code if it already appears in
the encounter's chart text — never invent one. Inventing a diagnosis to justify
a procedure is medical-necessity fraud.

Phase 0 uses literal presence of the code in the chart (in dotted "E11.9" or
undotted "E119" form, case-insensitive). A later phase can upgrade this to map
ICD codes to documented clinical conditions; the guardrail contract stays the
same, so this is a safe, conservative starting point.
"""

from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^A-Z0-9]")


def _normalize(code: str) -> str:
    """Uppercase and strip separators: 'e11.9' -> 'E119'."""
    return _NON_ALNUM.sub("", code.upper())


def icd_supported_by_chart(icd_code: str, chart_text: str) -> bool:
    """True if ``icd_code`` is documented in ``chart_text``.

    Matches both the dotted and undotted forms so 'E11.9' is found whether the
    chart wrote 'E11.9' or 'E119'. An empty/blank code is never "supported".
    """
    code = _normalize(icd_code)
    if not code:
        return False
    return code in _normalize(chart_text)
