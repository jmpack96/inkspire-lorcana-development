"""Durable Duels history/replay application workflows."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timezone
import gzip
import hashlib
import json
from typing import Any, ContextManager, Protocol
from uuid import UUID, uuid4

from sqlalchemy.engine import Connection, Engine

from lorcana.db.tx import transaction
from lorcana.duels.client import DuelsAuthenticationError, DuelsClient
from lorcana.duels.credentials import DuelsCredentialError, EnvironmentCredentialResolver
from lorcana.duels.features import FEATURE_EXTRACTOR_VERSION, extract_features
from lorcana.duels.history_parser import parse_history_game
from lorcana.duels.replay_parser import PARSER_VERSION, parse_replay
from lorcana.duels.repository import DuelsRepository
from lorcana.duels.types import DuelsSyncResult, ReplayProcessingResult

Clock = Callable[[], datetime]
UUIDFactory = Callable[[], UUID]
TransactionFactory = Callable[[], ContextManager[Connection]]
ReadConnectionFactory = Callable[[], ContextManager[Connection]]


class CredentialResolver(Protocol):
    def resolve(self, credential_ref: str) -> str: ...


class ClientFactory(Protocol):
    def __call__(self, token: str) -> DuelsClient: ...


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class DuelsServiceError(RuntimeError):
    pass


class DuelsService:
    def __init__(
        self,
        *,
        repository: DuelsRepository,
        read_connection_factory: ReadConnectionFactory,
        transaction_factory: TransactionFactory,
        credential_resolver: CredentialResolver | None = None,
        client_factory: ClientFactory = DuelsClient,
        clock: Clock = utc_now,
        uuid_factory: UUIDFactory = uuid4,
    ) -> None:
        self.repository = repository
        self.read_connection_factory = read_connection_factory
        self.transaction_factory = transaction_factory
        self.credential_resolver = credential_resolver or EnvironmentCredentialResolver()
        self.client_factory = client_factory
        self.clock = clock
        self.uuid_factory = uuid_factory

    @classmethod
    def from_engine(cls, engine: Engine, **kwargs: Any) -> "DuelsService":
        @contextmanager
        def read_connection():
            with engine.connect() as connection:
                yield connection

        return cls(
            repository=DuelsRepository(),
            read_connection_factory=read_connection,
            transaction_factory=lambda: transaction(engine),
            **kwargs,
        )

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("DuelsService clock must return timezone-aware datetimes")
        return now.astimezone(timezone.utc)

    def create_connection(
        self,
        member_id: UUID,
        *,
        credential_ref: str,
        label: str | None = None,
        provider_account_id: str | None = None,
    ) -> UUID:
        if not credential_ref.strip():
            raise ValueError("credential_ref must not be empty")
        connection_id = self.uuid_factory()
        now = self._now()
        with self.transaction_factory() as connection:
            self.repository.create_connection(
                connection,
                connection_id=connection_id,
                member_id=member_id,
                credential_ref=credential_ref.strip(),
                label=label.strip() if label and label.strip() else None,
                provider_account_id=(
                    provider_account_id.strip()
                    if provider_account_id and provider_account_id.strip()
                    else None
                ),
                now=now,
            )
        return connection_id

    def _record_connection_error(self, connection_id: UUID, error: Exception) -> None:
        auth_error = isinstance(error, (DuelsAuthenticationError, DuelsCredentialError))
        with self.transaction_factory() as connection:
            self.repository.record_sync_error(
                connection,
                connection_id,
                category=type(error).__name__,
                summary=str(error),
                auth_error=auth_error,
                now=self._now(),
            )

    def sync_history(self, connection_id: UUID, *, max_pages: int = 25) -> DuelsSyncResult:
        if max_pages <= 0:
            raise ValueError("max_pages must be positive")
        with self.read_connection_factory() as connection:
            linked = self.repository.get_connection(connection, connection_id)
        if linked is None:
            raise DuelsServiceError(f"Duels connection {connection_id} does not exist")
        if linked["status"] == "inactive":
            raise DuelsServiceError(f"Duels connection {connection_id} is inactive")

        pages = games_observed = new_games = 0
        was_exhausted = bool(linked["history_exhausted"])
        cursor = None if was_exhausted else linked["sync_cursor"]
        final_cursor = cursor
        exhausted = False
        client: DuelsClient | None = None

        try:
            with self.transaction_factory() as connection:
                self.repository.begin_sync(connection, connection_id, now=self._now())
            token = self.credential_resolver.resolve(linked["credential_ref"])
            client = self.client_factory(token)

            for _ in range(max_pages):
                page = client.fetch_history_page(cursor)
                pages += 1
                observed_at = self._now()
                parsed_games = [parse_history_game(payload) for payload in page.games]
                new_observations = 0
                with self.transaction_factory() as connection:
                    for game in parsed_games:
                        if self.repository.upsert_history_game(
                            connection,
                            connection_id=connection_id,
                            game=game,
                            observed_at=observed_at,
                        ):
                            new_observations += 1
                    games_observed += len(parsed_games)
                    new_games += new_observations
                    final_cursor = page.next_cursor
                    # Advance only after every observation on this page commits.
                    self.repository.save_sync_checkpoint(
                        connection,
                        connection_id,
                        cursor=final_cursor,
                        history_exhausted=False,
                        now=observed_at,
                    )

                if page.next_cursor is None:
                    exhausted = True
                    final_cursor = None
                    break
                if was_exhausted and new_observations == 0:
                    # History is newest-first. Once a recurring sync reaches a
                    # complete page already observed by this connection, older
                    # pages are behind the durable watermark.
                    exhausted = True
                    final_cursor = None
                    break
                cursor = page.next_cursor

            with self.transaction_factory() as connection:
                pending = self.repository.pending_replays(connection, connection_id, limit=500)
                self.repository.finish_sync(
                    connection,
                    connection_id,
                    cursor=final_cursor,
                    history_exhausted=exhausted,
                    now=self._now(),
                )
        except Exception as error:
            self._record_connection_error(connection_id, error)
            raise
        finally:
            if client is not None:
                client.close()

        return DuelsSyncResult(
            connection_id=connection_id,
            pages_fetched=pages,
            games_observed=games_observed,
            new_games=new_games,
            replay_candidates=len(pending),
            replay_revisions_created=0,
            normalizations_created=0,
            feature_sets_created=0,
            next_cursor=final_cursor,
            history_exhausted=exhausted,
        )

    def pending_replays(self, connection_id: UUID, *, limit: int = 500):
        if not 1 <= limit <= 5000:
            raise ValueError("limit must be between 1 and 5000")
        with self.read_connection_factory() as connection:
            return tuple(self.repository.pending_replays(connection, connection_id, limit=limit))

    def _decode_replay(self, source_bytes: bytes, game_id: str) -> tuple[str, dict[str, Any]]:
        if source_bytes[:2] == b"\x1f\x8b":
            encoding = "gzip"
            try:
                decoded = gzip.decompress(source_bytes)
            except OSError as error:
                raise DuelsServiceError(f"Replay {game_id} is invalid gzip") from error
        else:
            encoding = "identity"
            decoded = source_bytes
        try:
            payload = json.loads(decoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DuelsServiceError(f"Replay {game_id} is not valid UTF-8 JSON") from error
        if not isinstance(payload, dict):
            raise DuelsServiceError(f"Replay {game_id} root must be a JSON object")
        return encoding, payload

    def _persist_raw(
        self,
        *,
        connection_id: UUID,
        game_id: str,
        provider_replay_id: str | None,
        source_bytes: bytes,
        content_encoding: str,
        perspective: int | None,
        status: str,
        validation: dict[str, Any],
    ) -> tuple[UUID, bool]:
        with self.transaction_factory() as connection:
            return self.repository.insert_replay(
                connection,
                replay_id=self.uuid_factory(),
                connection_id=connection_id,
                game_id=game_id,
                provider_replay_id=provider_replay_id,
                perspective=perspective,
                fetched_at=self._now(),
                source_sha256=hashlib.sha256(source_bytes).hexdigest(),
                content_encoding=content_encoding,
                source_bytes=source_bytes,
                status=status,
                validation=validation,
            )

    def _existing_complete(self, replay_id: UUID) -> ReplayProcessingResult | None:
        with self.read_connection_factory() as connection:
            normalization = self.repository.get_normalization(connection, replay_id, PARSER_VERSION)
            if normalization is None:
                return None
            feature = self.repository.get_feature_set(
                connection,
                normalization["normalization_id"],
                FEATURE_EXTRACTOR_VERSION,
            )
            if feature is None:
                return None
        return ReplayProcessingResult(
            replay_id=replay_id,
            replay_created=False,
            normalization_id=normalization["normalization_id"],
            normalization_created=False,
            feature_set_id=feature["feature_set_id"],
            feature_set_created=False,
        )

    def process_replay(
        self,
        connection_id: UUID,
        game_id: str,
        *,
        force_refresh: bool = False,
    ) -> ReplayProcessingResult:
        with self.read_connection_factory() as connection:
            linked = self.repository.get_connection(connection, connection_id)
            observation = self.repository.get_observation(connection, connection_id, game_id)
            latest = self.repository.latest_replay(connection, connection_id, game_id)
        if linked is None:
            raise DuelsServiceError(f"Duels connection {connection_id} does not exist")
        if observation is None:
            raise DuelsServiceError(f"Game {game_id} is not visible to Duels connection {connection_id}")
        replay_url = observation["replay_url"]
        if not replay_url:
            raise DuelsServiceError(f"Game {game_id} does not currently have a replay URL")

        replay_created = False
        replay_id: UUID | None = None
        source_bytes: bytes

        same_provider_revision = (
            latest is not None
            and latest["provider_replay_id"] == observation["provider_replay_id"]
        )
        if not force_refresh and same_provider_revision and latest["status"] == "valid":
            complete = self._existing_complete(latest["replay_id"])
            if complete is not None:
                return complete
            # A prior attempt safely stored raw evidence but failed later. Resume
            # from those immutable bytes rather than losing work or refetching.
            source_bytes = bytes(latest["compressed_bytes"])
            replay_id = latest["replay_id"]
        else:
            try:
                token = self.credential_resolver.resolve(linked["credential_ref"])
                client = self.client_factory(token)
                try:
                    source_bytes = client.download_replay(replay_url)
                finally:
                    client.close()
            except Exception as error:
                self._record_connection_error(connection_id, error)
                raise

        try:
            content_encoding, replay_payload = self._decode_replay(source_bytes, game_id)
            replay_game_id = replay_payload.get("gameId")
            if replay_game_id is not None and str(replay_game_id) != game_id:
                raise DuelsServiceError(
                    f"Replay game ID {replay_game_id!r} does not match requested game {game_id!r}"
                )
            perspective = replay_payload.get("perspective")
            if perspective is not None and (
                isinstance(perspective, bool) or not isinstance(perspective, int)
            ):
                raise DuelsServiceError("Replay perspective must be an integer")
        except Exception as error:
            # Preserve the exact provider bytes even when validation fails. A
            # later parser/provider fix can inspect or re-fetch this evidence.
            if replay_id is None:
                try:
                    self._persist_raw(
                        connection_id=connection_id,
                        game_id=game_id,
                        provider_replay_id=observation["provider_replay_id"],
                        source_bytes=source_bytes,
                        content_encoding="unknown",
                        perspective=None,
                        status="invalid",
                        validation={"error_category": type(error).__name__, "error": str(error)[:1000]},
                    )
                except Exception:
                    pass
            raise

        if replay_id is None:
            replay_id, replay_created = self._persist_raw(
                connection_id=connection_id,
                game_id=game_id,
                provider_replay_id=observation["provider_replay_id"],
                source_bytes=source_bytes,
                content_encoding=content_encoding,
                perspective=perspective,
                status="valid",
                validation={"format": replay_payload.get("format"), "game_id": replay_game_id},
            )

        with self.read_connection_factory() as connection:
            existing_normalization = self.repository.get_normalization(
                connection, replay_id, PARSER_VERSION
            )
        if existing_normalization is None:
            normalized = parse_replay(replay_payload)
            if normalized.get("game", {}).get("game_id") != game_id:
                raise DuelsServiceError("Normalized replay game ID does not match source game")
            with self.transaction_factory() as connection:
                normalization_id, normalization_created = self.repository.insert_normalization(
                    connection,
                    normalization_id=self.uuid_factory(),
                    replay_id=replay_id,
                    parser_version=PARSER_VERSION,
                    schema_version=int(normalized["schema_version"]),
                    normalized=normalized,
                    normalized_sha256=canonical_json_sha256(normalized),
                    warnings=list(normalized.get("parser_warnings") or []),
                    created_at=self._now(),
                )
        else:
            normalization_id = existing_normalization["normalization_id"]
            normalization_created = False
            normalized = dict(existing_normalization["normalized"])

        with self.read_connection_factory() as connection:
            existing_features = self.repository.get_feature_set(
                connection, normalization_id, FEATURE_EXTRACTOR_VERSION
            )
        if existing_features is None:
            features = extract_features(normalized)
            with self.transaction_factory() as connection:
                feature_set_id, feature_set_created = self.repository.insert_feature_set(
                    connection,
                    feature_set_id=self.uuid_factory(),
                    normalization_id=normalization_id,
                    extractor_version=FEATURE_EXTRACTOR_VERSION,
                    features=features,
                    features_sha256=canonical_json_sha256(features),
                    created_at=self._now(),
                )
        else:
            feature_set_id = existing_features["feature_set_id"]
            feature_set_created = False

        return ReplayProcessingResult(
            replay_id=replay_id,
            replay_created=replay_created,
            normalization_id=normalization_id,
            normalization_created=normalization_created,
            feature_set_id=feature_set_id,
            feature_set_created=feature_set_created,
        )
