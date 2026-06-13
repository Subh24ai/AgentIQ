"""Prompt-injection firewall (OWASP LLM01 + LLM02).

The :class:`PromptInjectionGuard` scans untrusted text — both direct user input
and content fetched from external URLs — for known prompt-injection signatures
*before* it is allowed to enter the agent pipeline. It never raises on a match;
it always returns a :class:`ScanResult` so the caller decides how to react
(block, redact, downgrade trust, etc.).
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field


class ScanResult(BaseModel):
    """Outcome of scanning a piece of text for injection signatures."""

    is_safe: bool
    matched_patterns: list[str] = Field(default_factory=list)
    risk_score: float = 0.0


class PromptInjectionGuard:
    """Pattern-based detector for common prompt-injection / jailbreak attempts."""

    # (label, regex) pairs. Labels are human-readable for logging/alerting.
    # Categories: role-switching, system-prompt leakage, data exfiltration,
    # jailbreaks, and indirect-injection markers.
    _PATTERNS: list[tuple[str, str]] = [
        # --- role-switching / instruction override ---
        ("ignore_previous_instructions", r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions"),
        ("disregard_your", r"disregard\s+(your|all|previous|the)"),
        ("you_are_now", r"you\s+are\s+now\b"),
        ("forget_instructions", r"forget\s+(everything|all|your)\b"),
        # --- system-prompt leakage ---
        ("reveal_system_prompt", r"reveal\s+(your\s+)?(system\s+)?prompt"),
        ("print_instructions", r"print\s+(your\s+)?(instructions|system\s+prompt)"),
        ("repeat_system_prompt", r"(repeat|show|output)\s+(your\s+)?(system\s+)?(prompt|instructions)"),
        # --- data exfiltration ---
        ("send_to", r"\bsend\s+(this|it|all|everything)?\s*to\b"),
        ("forward_all", r"\bforward\s+all\b"),
        ("email_everything_to", r"email\s+(everything|all|this)\s+to\b"),
        # --- jailbreaks ---
        ("dan_jailbreak", r"\bDAN\b"),
        ("developer_mode", r"developer\s+mode"),
        ("unrestricted_mode", r"unrestricted\s+mode"),
        ("do_anything_now", r"do\s+anything\s+now"),
        # --- indirect-injection markers ---
        ("inject_marker", r"\[INJECT\]"),
        ("double_open_brace", r"\{\{"),
        ("double_close_brace", r"\}\}"),
        ("system_role_marker", r"\bSYSTEM\s*:"),
    ]

    def __init__(self) -> None:
        self._compiled: list[tuple[str, re.Pattern[str]]] = [
            (label, re.compile(pattern, re.IGNORECASE))
            for label, pattern in self._PATTERNS
        ]

    @property
    def pattern_count(self) -> int:
        return len(self._compiled)

    def scan(self, text: str) -> ScanResult:
        """Scan ``text`` and return a :class:`ScanResult`. Never raises."""

        if not text:
            return ScanResult(is_safe=True, matched_patterns=[], risk_score=0.0)

        matched: list[str] = []
        for label, pattern in self._compiled:
            if pattern.search(text):
                matched.append(label)

        if not matched:
            return ScanResult(is_safe=True, matched_patterns=[], risk_score=0.0)

        # More distinct signatures -> higher risk, clamped to [0, 1].
        risk = min(1.0, 0.5 + 0.15 * (len(matched) - 1))
        return ScanResult(is_safe=False, matched_patterns=matched, risk_score=risk)
