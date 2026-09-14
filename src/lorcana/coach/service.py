"""Access-controlled, versioned Coach analysis workflow."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, ContextManager
from uuid import UUID, uuid4

from sqlalchemy.engine import Connection, Engine

from lorcana.coach.analyzer import CoachAnalyzer
from lorcana.coach.evidence import compact_effective_actions
from lorcana.coach.repository import CoachRepository
from lorcana.coach.types import CoachAnalysisResult, CoachAnalyzerResult, CoachFindingDraft
from lorcana.db.tx import transaction

Clock = Callable[[], datetime]
UUIDFactory = Callable[[], UUID]
TransactionFactory = Callable[[], ContextManager[Connection]]
ReadConnectionFactory = Callable[[], ContextManager[Connection]]
CARD_ID_RE = re.compile(r"^\d+-\d+$")


class CoachError(RuntimeError):
    pass


class CoachAccessError(CoachError):
    pass


class CoachAnalysisInProgress(CoachError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _collect_card_ids(value: Any, output: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"id", "card_id", "cardId"} and isinstance(child, str) and CARD_ID_RE.fullmatch(child):
                output.add(child)
            _collect_card_ids(child, output)
    elif isinstance(value, list):
        for child in value:
            _collect_card_ids(child, output)
    elif isinstance(value, str) and CARD_ID_RE.fullmatch(value):
        output.add(value)


def _render_report(summary: str, findings: tuple[CoachFindingDraft, ...]) -> str:
    lines = ["# Lorcana Game Review", "", summary.strip()]
    if not findings:
        lines.extend(["", "## Findings", "", "No actionable findings were identified."])
        return "\n".join(lines)
    lines.extend(["", "## Findings", ""])
    for index, finding in enumerate(findings, start=1):
        lines.append(f"### {index}. {finding.category} — {finding.impact.upper()} impact")
        lines.append("")
        lines.append(finding.observation.strip())
        lines.append("")
        lines.append(f"**Recommendation:** {finding.recommendation.strip()}")
        evidence = []
        if finding.evidence_turns:
            evidence.append("turns " + ", ".join(str(value) for value in finding.evidence_turns))
        if finding.evidence_action_ids:
            evidence.append("actions " + ", ".join(str(value) for value in finding.evidence_action_ids))
        lines.append(
            f"**Evidence:** {'; '.join(evidence)} · **Confidence:** {finding.confidence:.0%} · "
            f"**Type:** {finding.claim_type}"
        )
        lines.append("")
    return "\n".join(lines).rstrip()


class CoachService:
    def __init__(
        self,
        *,
        repository: CoachRepository,
        read_connection_factory: ReadConnectionFactory,
        transaction_factory: TransactionFactory,
        clock: Clock = utc_now,
        uuid_factory: UUIDFactory = uuid4,
    ) -> None:
        self.repository = repository
        self.read_connection_factory = read_connection_factory
        self.transaction_factory = transaction_factory
        self.clock = clock
        self.uuid_factory = uuid_factory

    @classmethod
    def from_engine(cls, engine: Engine, **kwargs: Any) -> "CoachService":
        @contextmanager
        def reader():
            with engine.connect() as connection:
                yield connection
        return cls(
            repository=CoachRepository(),
            read_connection_factory=reader,
            transaction_factory=lambda: transaction(engine),
            **kwargs,
        )

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("CoachService clock must return timezone-aware datetimes")
        return value.astimezone(timezone.utc)

    def create_decklist(
        self,
        member_id: UUID,
        cards: Mapping[str, tuple[str, int] | int],
        *,
        name: str | None = None,
        source: str = "manual",
        source_reference: str | None = None,
        notes: str | None = None,
        catalog_snapshot_id: UUID | None = None,
    ) -> UUID:
        if not source.strip():
            raise ValueError("decklist source must not be empty")
        rows = []
        for card_id, value in cards.items():
            if isinstance(value, tuple):
                card_name, quantity = value
            else:
                card_name, quantity = card_id, value
            quantity = int(quantity)
            if quantity <= 0:
                raise ValueError("decklist quantities must be positive")
            rows.append({"card_id": str(card_id), "card_name": str(card_name), "quantity": quantity})
        if not rows:
            raise ValueError("decklist must contain at least one card")
        decklist_id = self.uuid_factory()
        with self.transaction_factory() as connection:
            self.repository.create_decklist(
                connection,
                decklist_id=decklist_id,
                member_id=member_id,
                catalog_snapshot_id=catalog_snapshot_id,
                name=_clean_optional(name),
                source=source.strip(),
                source_reference=_clean_optional(source_reference),
                notes=_clean_optional(notes),
                created_at=self._now(),
                cards=rows,
            )
        return decklist_id

    def _evidence_package(
        self,
        *,
        member_id: UUID,
        normalization_id: UUID,
        feature_set_id: UUID,
        catalog_snapshot_id: UUID,
        decklist_id: UUID | None,
    ) -> dict[str, Any]:
        with self.read_connection_factory() as connection:
            evidence = self.repository.evidence(
                connection,
                member_id=member_id,
                normalization_id=normalization_id,
                feature_set_id=feature_set_id,
            )
            if evidence is None:
                raise CoachAccessError("Replay evidence is not available to this member")
            snapshot = self.repository.catalog_snapshot(connection, catalog_snapshot_id)
            if snapshot is None:
                raise CoachError(f"Catalog snapshot {catalog_snapshot_id} does not exist")
            deck = None
            deck_cards = []
            if decklist_id is not None:
                deck_result = self.repository.decklist(connection, member_id, decklist_id)
                if deck_result is None:
                    raise CoachAccessError("Decklist is not available to this member")
                deck, deck_cards = deck_result

            normalized = dict(evidence["normalized"])
            features = dict(evidence["features"])
            effective_actions = normalized.get("effective_actions") or []
            if not isinstance(effective_actions, list):
                raise CoachError("Normalized replay effective_actions are invalid")
            compact_actions = compact_effective_actions(effective_actions)
            card_ids: set[str] = set()
            _collect_card_ids(normalized.get("decklist") or [], card_ids)
            _collect_card_ids(effective_actions, card_ids)
            for row in deck_cards:
                card_ids.add(row["card_id"])
            fact_rows = self.repository.catalog_facts(connection, catalog_snapshot_id, card_ids)

        facts = {
            row["card_id"]: {
                "card_id": row["card_id"],
                "name": row["name"],
                "version": row["version"],
                "set_code": row["set_code"],
                "set_name": row["set_name"],
                "collector_number": row["collector_number"],
                "ink_colors": row["ink_colors"],
                "cost": row["cost"],
                "inkable": row["inkable"],
                "classifications": row["classifications"],
                "card_type": row["card_type"],
                "rules_text": row["rules_text"],
            }
            for row in fact_rows
        }
        missing = sorted(card_ids - set(facts))
        return {
            "evidence_schema_version": 1,
            "game_id": evidence["game_id"],
            "replay_id": str(evidence["replay_id"]),
            "normalization": {
                "normalization_id": str(evidence["normalization_id"]),
                "parser_version": evidence["parser_version"],
                "normalized_sha256": evidence["normalized_sha256"],
                "game": normalized.get("game"),
                "mulligan": normalized.get("mulligan"),
                "undo_ranges": normalized.get("undo_ranges") or [],
                # Only effective actions are exposed as citable gameplay evidence.
                "effective_actions": compact_actions,
                "final_state": normalized.get("final_state"),
                "parser_warnings": normalized.get("parser_warnings") or [],
            },
            "features": {
                "feature_set_id": str(evidence["feature_set_id"]),
                "extractor_version": evidence["extractor_version"],
                "features_sha256": evidence["features_sha256"],
                "data": features,
            },
            "catalog": {
                "snapshot_id": str(catalog_snapshot_id),
                "source_name": snapshot["source_name"],
                "source_version": snapshot["source_version"],
                "facts": facts,
                "missing_card_ids": missing,
                "instruction": "Use catalog facts for card attributes. Do not infer missing card facts.",
            },
            "decklist": None if deck is None else {
                "decklist_id": str(deck["decklist_id"]),
                "name": deck["name"],
                "source": deck["source"],
                "cards": [dict(row) for row in deck_cards],
            },
        }

    @staticmethod
    def _validate_analyzer_result(result: CoachAnalyzerResult, evidence: dict[str, Any]) -> None:
        if not isinstance(result, CoachAnalyzerResult):
            raise CoachError("Analyzer returned an invalid result type")
        if not result.summary.strip():
            raise CoachError("Analyzer summary must not be empty")
        actions = evidence["normalization"]["effective_actions"]
        valid_action_ids = {
            action.get("seq") for action in actions
            if isinstance(action, dict) and isinstance(action.get("seq"), int)
        }
        valid_turns = {
            action.get("gameplay_turn") for action in actions
            if isinstance(action, dict) and isinstance(action.get("gameplay_turn"), int)
        }
        for finding in result.findings:
            if not isinstance(finding, CoachFindingDraft):
                raise CoachError("Analyzer findings must use CoachFindingDraft")
            if not finding.category.strip() or not finding.observation.strip() or not finding.recommendation.strip():
                raise CoachError("Coach findings require category, observation, and recommendation")
            if finding.impact not in {"low", "medium", "high"}:
                raise CoachError(f"Invalid finding impact: {finding.impact}")
            if finding.claim_type not in {"fact", "inference"}:
                raise CoachError(f"Invalid finding claim_type: {finding.claim_type}")
            if not 0.0 <= float(finding.confidence) <= 1.0:
                raise CoachError("Finding confidence must be between 0 and 1")
            if not finding.evidence_action_ids and not finding.evidence_turns:
                raise CoachError("Every finding must cite at least one action or turn")
            if any(action_id not in valid_action_ids for action_id in finding.evidence_action_ids):
                raise CoachError("Finding cited an action that is not in effective replay evidence")
            if any(turn not in valid_turns for turn in finding.evidence_turns):
                raise CoachError("Finding cited a turn that is not in effective replay evidence")

    def analyze(
        self,
        *,
        member_id: UUID,
        normalization_id: UUID,
        feature_set_id: UUID,
        catalog_snapshot_id: UUID,
        analyzer: CoachAnalyzer,
        decklist_id: UUID | None = None,
        analysis_config: Mapping[str, Any] | None = None,
        restart_running: bool = False,
    ) -> CoachAnalysisResult:
        evidence = self._evidence_package(
            member_id=member_id,
            normalization_id=normalization_id,
            feature_set_id=feature_set_id,
            catalog_snapshot_id=catalog_snapshot_id,
            decklist_id=decklist_id,
        )
        config = dict(analysis_config or {})
        analyzer_input = {**evidence, "analysis_config": config}
        input_sha = canonical_sha256(analyzer_input)
        idempotency_key = canonical_sha256({
            "member_id": str(member_id),
            "normalization_id": str(normalization_id),
            "feature_set_id": str(feature_set_id),
            "catalog_snapshot_id": str(catalog_snapshot_id),
            "decklist_id": str(decklist_id) if decklist_id else None,
            "analyzer_provider": analyzer.provider,
            "analyzer_model": analyzer.model,
            "prompt_version": analyzer.prompt_version,
            "analysis_config": config,
            "input_sha256": input_sha,
        })
        now = self._now()
        analysis_run_id = self.uuid_factory()
        with self.transaction_factory() as connection:
            self.repository.lock_idempotency(connection, idempotency_key)
            existing = self.repository.run_by_idempotency(connection, idempotency_key, for_update=True)
            if existing is None:
                self.repository.create_run(
                    connection,
                    analysis_run_id=analysis_run_id,
                    member_id=member_id,
                    normalization_id=normalization_id,
                    feature_set_id=feature_set_id,
                    catalog_snapshot_id=catalog_snapshot_id,
                    decklist_id=decklist_id,
                    analyzer_provider=analyzer.provider,
                    analyzer_model=analyzer.model,
                    prompt_version=analyzer.prompt_version,
                    analysis_config=config,
                    input_sha256=input_sha,
                    idempotency_key=idempotency_key,
                    status="running",
                    started_at=now,
                )
            elif existing["status"] == "succeeded":
                report = self.repository.report_for_run(connection, existing["analysis_run_id"], member_id=member_id)
                if report is None:
                    raise CoachError("Succeeded Coach run is missing its report")
                return CoachAnalysisResult(
                    analysis_run_id=existing["analysis_run_id"],
                    report_id=report["report_id"],
                    cached=True,
                    finding_count=self.repository.finding_count(connection, existing["analysis_run_id"]),
                    content=report["content"],
                )
            elif existing["status"] == "running":
                if not restart_running:
                    raise CoachAnalysisInProgress(
                        f"Coach analysis {existing['analysis_run_id']} is already running"
                    )
                analysis_run_id = existing["analysis_run_id"]
                self.repository.restart_run(connection, analysis_run_id, started_at=now)
            else:
                analysis_run_id = existing["analysis_run_id"]
                self.repository.restart_run(connection, analysis_run_id, started_at=now)

        try:
            result = analyzer.analyze(analyzer_input)
            self._validate_analyzer_result(result, analyzer_input)
            report_content = _render_report(result.summary, result.findings)
            completed_at = self._now()
            finding_rows = []
            for ordinal, finding in enumerate(result.findings, start=1):
                finding_rows.append({
                    "finding_id": self.uuid_factory(),
                    "analysis_run_id": analysis_run_id,
                    "ordinal": ordinal,
                    "category": finding.category.strip(),
                    "impact": finding.impact,
                    "confidence": float(finding.confidence),
                    "claim_type": finding.claim_type,
                    "observation": finding.observation.strip(),
                    "recommendation": finding.recommendation.strip(),
                    "evidence_action_ids": list(finding.evidence_action_ids),
                    "evidence_turns": list(finding.evidence_turns),
                    "payload": dict(finding.payload),
                })
            report_id = self.uuid_factory()
            with self.transaction_factory() as connection:
                self.repository.complete(
                    connection,
                    analysis_run_id=analysis_run_id,
                    findings=finding_rows,
                    report_id=report_id,
                    report_content=report_content,
                    usage=result.usage,
                    completed_at=completed_at,
                )
        except Exception as error:
            with self.transaction_factory() as connection:
                self.repository.mark_failed(
                    connection,
                    analysis_run_id,
                    completed_at=self._now(),
                    error=error,
                )
            raise

        return CoachAnalysisResult(
            analysis_run_id=analysis_run_id,
            report_id=report_id,
            cached=False,
            finding_count=len(result.findings),
            content=report_content,
        )

    def report(self, member_id: UUID, analysis_run_id: UUID) -> CoachAnalysisResult | None:
        with self.read_connection_factory() as connection:
            row = self.repository.report_for_run(connection, analysis_run_id, member_id=member_id)
            if row is None:
                return None
            count = self.repository.finding_count(connection, analysis_run_id)
        return CoachAnalysisResult(
            analysis_run_id=analysis_run_id,
            report_id=row["report_id"],
            cached=True,
            finding_count=int(count),
            content=row["content"],
        )

    def latest_report_for_game(self, member_id: UUID, game_id: str) -> CoachAnalysisResult | None:
        game = game_id.strip()
        if not game:
            return None
        with self.read_connection_factory() as connection:
            row = self.repository.latest_report_for_game(
                connection,
                member_id=member_id,
                game_id=game,
            )
            if row is None:
                return None
            count = self.repository.finding_count(connection, row["analysis_run_id"])
        return CoachAnalysisResult(
            analysis_run_id=row["analysis_run_id"],
            report_id=row["report_id"],
            cached=True,
            finding_count=count,
            content=row["content"],
        )
