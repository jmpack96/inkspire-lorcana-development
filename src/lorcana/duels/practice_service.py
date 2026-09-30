"""Private practice reports from already-synced evidence; no network/model calls."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import re

from lorcana.duels.practice import RAMP_CARDS, colors_label, deck_fingerprint, opening_metrics
from lorcana.duels.practice_repository import PracticeRepository

HISTORY_LIMIT = 2000
OPENINGS_LIMIT = 100


class PracticeService:
    def __init__(self, *, repository, read_connection_factory, clock=lambda: datetime.now(timezone.utc)):
        self.repository = repository
        self.read_connection_factory = read_connection_factory
        self.clock = clock

    @classmethod
    def from_engine(cls, engine):
        @contextmanager
        def reader():
            with engine.connect() as connection:
                yield connection
        return cls(repository=PracticeRepository(), read_connection_factory=reader)

    def report(self, member_id, *, openings=False, days=30, ranked=None, deck=None,
               profile="general", cards=None):
        if type(days) is not int or not 1 <= days <= 365:
            raise ValueError("Days must be between 1 and 365.")
        if ranked is not None and type(ranked) is not bool:
            raise ValueError("Ranked must be true, false, or omitted.")
        if profile not in {"general", "ruby_sapphire"}:
            raise ValueError("Unknown opening profile.")
        deck = deck.strip().lower() if deck else None
        if deck and not re.fullmatch(r"[0-9a-f]{12,64}", deck):
            raise ValueError("Use a deck ID shown by /practice summary (at least 12 characters).")
        targets = RAMP_CARDS if profile == "ruby_sapphire" else ()
        if cards is not None:
            targets = tuple(dict.fromkeys(c.strip() for c in cards.split(",") if c.strip()))
            if not targets or len(targets) > 8 or len(cards) > 300:
                raise ValueError("Provide 1–8 comma-separated full card names or Duels card IDs (300 characters maximum).")
        now = self.clock()
        with self.read_connection_factory() as connection:
            status = self.repository.sync_status(connection, member_id=member_id)
            rows = self.repository.history(connection, member_id=member_id,
                since=now - timedelta(days=days), until=now, ranked=ranked, limit=HISTORY_LIMIT + 1)
            truncated = len(rows) > HISTORY_LIMIT
            rows = rows[:HISTORY_LIMIT]
            for row in rows:
                row["deck_id"] = deck_fingerprint(row.pop("decklist", None))
            if deck:
                matches = {r["deck_id"] for r in rows if r["deck_id"] and r["deck_id"].startswith(deck)}
                if len(matches) > 1:
                    raise ValueError("That deck prefix is ambiguous; use a longer deck ID.")
                rows = [r for r in rows if r["deck_id"] in matches]
            if profile == "ruby_sapphire":
                rows = [r for r in rows if colors_label(r["your_deck_colors"]) == "Ruby/Sapphire"]
            evidence_rows = [r for r in rows if r["normalization_id"] is not None]
            metrics = []
            if openings:
                sample = evidence_rows[:OPENINGS_LIMIT]
                payloads = self.repository.opening_evidence(connection, member_id=member_id,
                    normalization_ids=[r["normalization_id"] for r in sample])
                for row in sample:
                    normalized = payloads.get(row["normalization_id"])
                    if normalized is None:
                        continue
                    metric = opening_metrics(normalized, targets)
                    metric["game_id"] = row["game_id"]
                    metric["went_first"] = row["went_first"]
                    metrics.append(metric)
        return {"days": days, "ranked": ranked, "deck": deck, "profile": profile,
                "targets": targets, "rows": rows, "status": status, "truncated": truncated,
                "evidence_count": len(evidence_rows), "metrics": metrics,
                "openings_limited": openings and len(evidence_rows) > OPENINGS_LIMIT}
