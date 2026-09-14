SELECT
            m.match_id,
            m.event_id,
            m.round_id,

            m.player1_id,
            m.player2_id,

            m.winner_id,
            m.is_draw,

            e.start_datetime,

            COALESCE(p.phase_order, 0)
                AS phase_order,

            COALESCE(r.round_number, 0)
                AS round_number

        FROM matches m

        JOIN events e
            ON e.event_id = m.event_id

        LEFT JOIN rounds r
            ON r.round_id = m.round_id

        LEFT JOIN phases p
            ON p.phase_id = r.phase_id

        WHERE
            m.status = 'COMPLETE'

            AND m.is_bye = 0
            AND m.is_ghost_match = 0

            -- Critical safety check:
            -- only confirmed 1v1 matches.
            AND m.participant_count = 2

            AND m.player1_id IS NOT NULL
            AND m.player2_id IS NOT NULL

            AND m.player1_id != m.player2_id

            AND (
                m.winner_id IS NOT NULL
                OR m.is_draw = 1
            )

            AND e.start_datetime IS NOT NULL

        ORDER BY
            e.start_datetime,
            m.event_id,
            phase_order,
            round_number,
            m.match_id
