"""Typed analyzer contract and persisted Coach response DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class CoachFindingDraft:
    category: str
    impact: str
    confidence: float
    claim_type: str
    observation: str
    recommendation: str
    evidence_action_ids: tuple[int, ...] = field(default_factory=tuple)
    evidence_turns: tuple[int, ...] = field(default_factory=tuple)
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CoachAnalyzerResult:
    summary: str
    findings: tuple[CoachFindingDraft, ...]
    usage: dict[str, Any] | None = None


@dataclass(frozen=True)
class CoachAnalysisResult:
    analysis_run_id: UUID
    report_id: UUID
    cached: bool
    finding_count: int
    content: str
