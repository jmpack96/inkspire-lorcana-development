"""Bounded, restartable backfill: python -m lorcana.duels.backfill_read_models."""
import argparse
import time

from sqlalchemy import or_, select, text

from lorcana.bootstrap import ApplicationResources
from lorcana.db.schema.duels import duels_normalizations as sources, duels_read_models as models
from lorcana.duels.opening_projection import PROJECTION_VERSION
from lorcana.duels.replay_parser import PARSER_VERSION
from lorcana.duels.repository import DuelsRepository


def backfill_batch(engine, *, batch_size=25):
    if type(batch_size) is not int or not 1 <= batch_size <= 100:
        raise ValueError("batch_size must be between 1 and 100")
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL statement_timeout = '15s'"))
        # Only one backfill process at a time; imports do not take this lock.
        if not connection.scalar(text("SELECT pg_try_advisory_xact_lock(134731, 1)")):
            return {"processed": 0, "busy": True}
        rows = connection.execute(select(sources.c.normalization_id, sources.c.normalized)
            .select_from(sources.outerjoin(models, models.c.normalization_id == sources.c.normalization_id))
            .where(sources.c.status == "valid", sources.c.parser_version == PARSER_VERSION,
                   or_(models.c.normalization_id.is_(None), models.c.version != PROJECTION_VERSION))
            .order_by(sources.c.normalization_id).limit(batch_size)).mappings().all()
        repository = DuelsRepository()
        for row in rows:
            repository.store_read_model(connection, row["normalization_id"], dict(row["normalized"]))
    return {"processed": len(rows), "busy": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--max-batches", type=int, default=20)
    parser.add_argument("--pause-seconds", type=float, default=1)
    args = parser.parse_args(argv)
    if not 1 <= args.max_batches <= 1000 or not 0 <= args.pause_seconds <= 10:
        parser.error("max-batches must be 1–1000 and pause-seconds must be 0–10")
    resources = ApplicationResources.from_env()
    total = 0
    try:
        for number in range(args.max_batches):
            result = backfill_batch(resources.engine, batch_size=args.batch_size)
            total += result["processed"]
            print(f"batch={number + 1} processed={result['processed']} total={total} busy={result['busy']}", flush=True)
            if result["busy"]:
                print("Another backfill is active; retry later.", flush=True)
                return 1
            if result["processed"] == 0:
                print("Backfill complete for the current parser version.", flush=True)
                return 0
            if number + 1 < args.max_batches:
                time.sleep(args.pause_seconds)
        print("Batch limit reached. Rerun the same command to continue.", flush=True)
    finally:
        resources.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
