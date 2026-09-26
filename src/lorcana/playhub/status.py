"""Shared interpretation of Play Hub's raw event status fields."""

from sqlalchemy import and_, func, or_

from lorcana.db.schema.playhub import playhub_events


def event_is_in_progress_clause():
    # Removing separators also handles the source's camelCase `inProgress`.
    columns = tuple(
        func.upper(
            func.replace(
                func.replace(
                    func.replace(func.trim(func.coalesce(column, "")), "_", ""),
                    "-", "",
                ),
                " ", "",
            )
        )
        for column in (
            playhub_events.c.display_status,
            playhub_events.c.event_status,
            playhub_events.c.lifecycle_status,
        )
    )
    active = ("LIVE", "ACTIVE", "RUNNING", "STARTED", "INPROGRESS", "EVENTINPROGRESS")
    terminal = (
        "COMPLETE", "COMPLETED", "FINISHED", "ENDED", "CANCELLED", "CANCELED",
        "EVENTCOMPLETE", "EVENTCOMPLETED", "EVENTFINISHED", "EVENTENDED",
        "EVENTCANCELLED", "EVENTCANCELED",
    )
    # A finished/cancelled field must veto stale in-progress data in another field.
    return and_(
        or_(*(column.in_(active) for column in columns)),
        *(column.not_in(terminal) for column in columns),
    )
