"""Application workflow for reproducible Elo builds and publication."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, ContextManager
from uuid import UUID, uuid4

from sqlalchemy.engine import Connection, Engine

from lorcana.db.tx import transaction
from lorcana.ratings.elo import ALGORITHM, K_FACTOR, STARTING_RATING, EloCalculator
from lorcana.ratings.policy import GlobalEloV1Policy, RatingPolicy
from lorcana.ratings.repository import RatingRepository
from lorcana.ratings.types import RatingBuildResult, RatingRunInput

Clock = Callable[[], datetime]
UUIDFactory = Callable[[], UUID]
ConnectionFactory = Callable[[], ContextManager[Connection]]
TransactionFactory = Callable[[], ContextManager[Connection]]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_input(row: RatingRunInput) -> bytes:
    payload = [
        row.sequence_number,
        row.match_id,
        row.event_id,
        row.event_start_datetime.astimezone(timezone.utc).isoformat(timespec="microseconds"),
        row.phase_order,
        row.round_number,
        row.player1_id,
        row.player2_id,
        row.winner_id,
        row.is_draw,
    ]
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"


def ordered_input_digest(rows: Iterable[RatingRunInput]) -> str:
    """Hash every immutable rating fact in sequence order."""
    digest = hashlib.sha256()
    for row in rows:
        digest.update(_canonical_input(row))
    return digest.hexdigest()


class RatingBuildError(RuntimeError):
    """Raised when a run cannot be safely built or published."""


class RatingService:
    """Build immutable rating runs from Play Hub source facts.

    Source candidates and snapshotted inputs are read on a separate connection
    from the write transaction. This lets PostgreSQL stream hundreds of
    thousands of rows without mixing a server-side cursor and writes on one
    connection, while the write side still commits each build stage atomically.
    """

    def __init__(
        self,
        *,
        repository: RatingRepository,
        read_connection_factory: ConnectionFactory,
        transaction_factory: TransactionFactory,
        policy: RatingPolicy | None = None,
        clock: Clock = utc_now,
        uuid_factory: UUIDFactory = uuid4,
        input_batch_size: int = 5_000,
        history_batch_size: int = 10_000,
        starting_rating: float = STARTING_RATING,
        k_factor: float = K_FACTOR,
    ) -> None:
        if input_batch_size <= 0 or history_batch_size <= 0:
            raise ValueError("Rating batch sizes must be positive")
        # EloCalculator is the canonical parameter validator.
        EloCalculator(starting_rating=starting_rating, k_factor=k_factor)
        self.repository = repository
        self.read_connection_factory = read_connection_factory
        self.transaction_factory = transaction_factory
        self.policy = policy or GlobalEloV1Policy()
        self.clock = clock
        self.uuid_factory = uuid_factory
        self.input_batch_size = input_batch_size
        self.history_batch_size = history_batch_size
        self.starting_rating = float(starting_rating)
        self.k_factor = float(k_factor)

    @classmethod
    def from_engine(
        cls,
        engine: Engine,
        *,
        repository: RatingRepository | None = None,
        policy: RatingPolicy | None = None,
        **kwargs: Any,
    ) -> "RatingService":
        @contextmanager
        def read_connection() -> Iterable[Connection]:
            with engine.connect() as connection:
                yield connection

        return cls(
            repository=repository or RatingRepository(),
            read_connection_factory=read_connection,
            transaction_factory=lambda: transaction(engine),
            policy=policy,
            **kwargs,
        )

    @property
    def parameters(self) -> dict[str, float]:
        return {
            "starting_rating": self.starting_rating,
            "k_factor": self.k_factor,
        }

    def build(self, *, notes: str | None = None) -> RatingBuildResult:
        run_id = self.uuid_factory()
        started_at = self.clock()
        self._require_aware(started_at)
        with self.transaction_factory() as connection:
            self.repository.create_run(
                connection,
                rating_run_id=run_id,
                algorithm="elo",
                algorithm_version=ALGORITHM,
                policy_version=self.policy.version,
                parameters=self.parameters,
                started_at=started_at,
                notes=notes,
            )

        try:
            input_count, digest, exclusion_counts = self._snapshot(run_id)
            player_count = self._calculate_and_validate(run_id, input_count)
        except Exception as error:
            self._record_failure(run_id, error)
            raise

        return RatingBuildResult(
            rating_run_id=run_id,
            input_count=input_count,
            player_count=player_count,
            ordered_input_digest=digest,
            exclusion_counts=exclusion_counts,
            status="validated",
        )

    def build_and_publish(
        self,
        *,
        publication_name: str = "global_elo",
        published_by: str | None = None,
        notes: str | None = None,
    ) -> RatingBuildResult:
        result = self.build(notes=notes)
        self.publish(
            result.rating_run_id,
            publication_name=publication_name,
            published_by=published_by,
        )
        return RatingBuildResult(
            rating_run_id=result.rating_run_id,
            input_count=result.input_count,
            player_count=result.player_count,
            ordered_input_digest=result.ordered_input_digest,
            exclusion_counts=result.exclusion_counts,
            status="published",
            publication_name=publication_name,
        )

    def preview_source(self) -> tuple[int, str, dict[str, int]]:
        """Hash the current eligible source without creating a rating run.

        This intentionally makes automated refreshes scan the candidates twice
        when data changed. The extra read is far cheaper than writing and then
        deleting a full duplicate run when nothing changed, and avoids PostgreSQL
        table/index churn from daily no-op Elo rebuilds.
        """
        digest = hashlib.sha256()
        exclusions: Counter[str] = Counter()
        included = 0
        with self.read_connection_factory() as reader:
            for candidate in self.repository.iter_candidates(reader):
                decision = self.policy.evaluate(candidate)
                if not decision.included:
                    exclusions[decision.reason] += 1
                    continue
                if (
                    candidate.player1_id is None
                    or candidate.player2_id is None
                    or candidate.event_start_datetime is None
                ):
                    raise RatingBuildError(
                        f"Policy {self.policy.version} included incomplete match {candidate.match_id}"
                    )
                self._require_aware(candidate.event_start_datetime)
                included += 1
                row = RatingRunInput(
                    sequence_number=included,
                    match_id=candidate.match_id,
                    event_id=candidate.event_id,
                    event_start_datetime=candidate.event_start_datetime,
                    phase_order=candidate.phase_order,
                    round_number=candidate.round_number,
                    player1_id=candidate.player1_id,
                    player2_id=candidate.player2_id,
                    winner_id=candidate.winner_id,
                    is_draw=candidate.is_draw,
                )
                digest.update(_canonical_input(row))
        return included, digest.hexdigest(), dict(sorted(exclusions.items()))

    def build_and_publish_if_changed(
        self,
        *,
        publication_name: str = "global_elo",
        published_by: str | None = None,
        notes: str | None = None,
    ) -> RatingBuildResult:
        """Publish a new run only when its immutable source facts changed."""
        input_count, digest, exclusions = self.preview_source()
        with self.read_connection_factory() as connection:
            current = self.repository.resolve_publication(connection, publication_name)
        if (
            current is not None
            and current["algorithm"] == "elo"
            and current["algorithm_version"] == ALGORITHM
            and current["policy_version"] == self.policy.version
            and dict(current["parameters"] or {}) == self.parameters
            and current["input_count"] == input_count
            and current["ordered_input_digest"] == digest
        ):
            # A no-op refresh is still an opportunity to enforce retention.
            # This clears superseded runs left behind by older deployments or
            # interrupted maintenance without manufacturing a duplicate run.
            with self.transaction_factory() as connection:
                self.repository.prune_unretained_runs(connection)
            return RatingBuildResult(
                rating_run_id=current["rating_run_id"],
                input_count=input_count,
                player_count=int(current["player_count"] or 0),
                ordered_input_digest=digest,
                exclusion_counts=dict(current["exclusion_counts"] or exclusions),
                status="unchanged",
                publication_name=publication_name,
            )
        return self.build_and_publish(
            publication_name=publication_name,
            published_by=published_by,
            notes=notes,
        )

    def publish(
        self,
        rating_run_id: UUID,
        *,
        publication_name: str = "global_elo",
        published_by: str | None = None,
    ) -> None:
        if not publication_name.strip():
            raise ValueError("publication_name must not be empty")
        published_at = self.clock()
        self._require_aware(published_at)
        with self.transaction_factory() as connection:
            status = self.repository.get_run_status(
                connection,
                rating_run_id,
                for_update=True,
            )
            if status is None:
                raise RatingBuildError(f"Rating run {rating_run_id} does not exist")
            if status not in {"validated", "published"}:
                raise RatingBuildError(
                    f"Rating run {rating_run_id} is {status!r}; only validated runs can be published"
                )
            self.repository.publish(
                connection,
                publication_name=publication_name,
                rating_run_id=rating_run_id,
                published_at=published_at,
                published_by=published_by,
            )
            # Rating storage is deliberately bounded. The publication protects
            # exactly its current and previous generations; all older completed
            # runs are removed in the same transaction as pointer rotation.
            self.repository.prune_unretained_runs(connection)

    def _snapshot(self, run_id: UUID) -> tuple[int, str, dict[str, int]]:
        digest = hashlib.sha256()
        exclusions: Counter[str] = Counter()
        included = 0
        batch: list[RatingRunInput] = []

        with self.read_connection_factory() as reader, self.transaction_factory() as writer:
            for candidate in self.repository.iter_candidates(reader):
                decision = self.policy.evaluate(candidate)
                if not decision.included:
                    exclusions[decision.reason] += 1
                    continue

                # A policy that includes incomplete calculation facts is a code bug.
                if (
                    candidate.player1_id is None
                    or candidate.player2_id is None
                    or candidate.event_start_datetime is None
                ):
                    raise RatingBuildError(
                        f"Policy {self.policy.version} included incomplete match {candidate.match_id}"
                    )
                self._require_aware(candidate.event_start_datetime)
                included += 1
                row = RatingRunInput(
                    sequence_number=included,
                    match_id=candidate.match_id,
                    event_id=candidate.event_id,
                    event_start_datetime=candidate.event_start_datetime,
                    phase_order=candidate.phase_order,
                    round_number=candidate.round_number,
                    player1_id=candidate.player1_id,
                    player2_id=candidate.player2_id,
                    winner_id=candidate.winner_id,
                    is_draw=candidate.is_draw,
                )
                digest.update(_canonical_input(row))
                batch.append(row)
                if len(batch) >= self.input_batch_size:
                    self.repository.insert_run_inputs(writer, run_id, batch)
                    batch.clear()

            if batch:
                self.repository.insert_run_inputs(writer, run_id, batch)

            self.repository.finish_snapshot(
                writer,
                rating_run_id=run_id,
                input_count=included,
                ordered_input_digest=digest.hexdigest(),
                exclusion_counts=dict(sorted(exclusions.items())),
            )

        return included, digest.hexdigest(), dict(sorted(exclusions.items()))

    def _calculate_and_validate(self, run_id: UUID, input_count: int) -> int:
        calculator = EloCalculator(
            starting_rating=self.starting_rating,
            k_factor=self.k_factor,
        )
        history_batch: list[dict[str, Any]] = []
        seen_inputs = 0

        with self.read_connection_factory() as reader, self.transaction_factory() as writer:
            for run_input in self.repository.iter_run_inputs(reader, run_id):
                seen_inputs += 1
                if run_input.sequence_number != seen_inputs:
                    raise RatingBuildError(
                        f"Rating run {run_id} has non-contiguous input sequence at {run_input.sequence_number}"
                    )
                history = calculator.process(run_input.as_rating_match())
                if len(history) != 2:
                    raise RatingBuildError(
                        f"Snapshotted rating input {run_input.match_id} failed calculator validation"
                    )
                for item in history:
                    history_batch.append(
                        {
                            "rating_run_id": run_id,
                            "sequence_number": run_input.sequence_number,
                            "player_id": item.player_id,
                            "match_id": item.match_id,
                            "event_id": item.event_id,
                            "rating_before": item.rating_before,
                            "rating_after": item.rating_after,
                            "rating_change": item.rating_change,
                            "opponent_id": item.opponent_id,
                            "opponent_rating_before": item.opponent_rating_before,
                            "result": item.result,
                        }
                    )
                if len(history_batch) >= self.history_batch_size:
                    self.repository.insert_history(writer, history_batch)
                    history_batch.clear()

            if history_batch:
                self.repository.insert_history(writer, history_batch)

            if seen_inputs != input_count:
                raise RatingBuildError(
                    f"Rating run {run_id} expected {input_count} inputs but read {seen_inputs}"
                )
            if calculator.invalid_matches:
                raise RatingBuildError(
                    f"Rating run {run_id} had {calculator.invalid_matches} invalid snapshotted matches"
                )
            if calculator.matches_processed != input_count:
                raise RatingBuildError(
                    f"Rating run {run_id} processed {calculator.matches_processed} of {input_count} inputs"
                )

            current_rows: list[dict[str, Any]] = []
            for player_id, state in calculator.players.items():
                if not all(math.isfinite(value) for value in (state.rating, state.peak)):
                    raise RatingBuildError(f"Non-finite rating for player {player_id}")
                if state.matches != state.wins + state.losses + state.draws:
                    raise RatingBuildError(f"Invalid record totals for player {player_id}")
                current_rows.append(
                    {
                        "rating_run_id": run_id,
                        "player_id": player_id,
                        "rating": state.rating,
                        "matches_played": state.matches,
                        "wins": state.wins,
                        "losses": state.losses,
                        "draws": state.draws,
                        "peak_rating": state.peak,
                    }
                )
            self.repository.insert_current(writer, current_rows)

            history_count = self.repository.count_history(writer, run_id)
            current_count = self.repository.count_current(writer, run_id)
            if history_count != input_count * 2:
                raise RatingBuildError(
                    f"Rating run {run_id} expected {input_count * 2} history rows, found {history_count}"
                )
            if current_count != len(calculator.players):
                raise RatingBuildError(
                    f"Rating run {run_id} expected {len(calculator.players)} current rows, found {current_count}"
                )

            self.repository.mark_validated(
                writer,
                rating_run_id=run_id,
                completed_at=self.clock(),
                player_count=len(calculator.players),
            )
        return len(calculator.players)

    def _record_failure(self, run_id: UUID, error: Exception) -> None:
        try:
            completed_at = self.clock()
            self._require_aware(completed_at)
            summary = f"{type(error).__name__}: {error}"[:4_000]
            with self.transaction_factory() as connection:
                self.repository.mark_failed(
                    connection,
                    rating_run_id=run_id,
                    completed_at=completed_at,
                    notes=summary,
                )
                # Failed builds can contain hundreds of thousands of snapshotted
                # inputs/history rows. They are not a publication generation, so
                # remove them immediately rather than waiting for a later publish.
                self.repository.prune_unretained_runs(connection)
        except Exception:
            # Never replace the original build error with failure-reporting noise.
            pass

    @staticmethod
    def _require_aware(value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Rating timestamps must be timezone-aware")
