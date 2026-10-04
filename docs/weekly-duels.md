# Weekly Duels report

`/duels-weekly` displays all active team members with a configured Duels connection,
including players with zero games. The invoking user must be linked to an active
team member, as with `/duels-summary`. The command uses a rolling seven-day window.

Each player gets their game count, W-L-D record for each color combination played,
The report also shows one team-wide opponent color combination with the largest
number of losses, pooled across every player and every deck they played.
Ties are shown. Unknown outcomes and unknown opponent colors are identified separately.
Deck colors describe a color grouping, not an exact deck list. All queues and team
practice games count. Multiple accounts are deduplicated per member/game.

The gateway bot automatically posts to the configured channel every Sunday
at 09:00 America/New_York, respecting daylight saving time. Each scheduled report
covers the previous Sunday 09:00 through this Sunday 09:00, excluding the endpoint.
It polls once a minute and catches up the latest due report when restarted.
It does not backfill every missed week. Initial deployment after a Sunday boundary
posts the latest completed week immediately.

## Apply and deploy

From the repository directory, with the downloaded patch at the supplied path:

```sh
git apply --check /path/to/weekly-duels-summary.patch
git apply /path/to/weekly-duels-summary.patch
python -m alembic upgrade head
```

Run the migration against your production database before restarting the bot.
Set this variable on your Railway **bot service**:

```env
DISCORD_WEEKLY_DUELS_CHANNEL_ID=1554958872639184896
```

Leave the variable unset to disable automatic posts; `/duels-weekly` remains available.
Invalid or empty IDs are rejected at startup. Changing channels creates a separate
weekly delivery record and can post the latest completed week to the new channel.
Commit and deploy through your normal Railway workflow. The bot registers the new
slash command on startup. It needs View Channel, Send Messages, and Embed Links
permissions in the destination channel. No additional scheduled worker job or
ChatGPT task is needed; the running gateway bot handles delivery.

Manual responses use the existing paginator. Automatic reports send each bounded
page so the entire report remains readable after interactive views expire.
A database lease prevents concurrent bot instances from sending the same report;
persisted pages and progress allow retries to resume after completed pages. As with
other Discord outbound messages, a crash between Discord accepting a page and the
DB recording progress can duplicate that page. Delivery is retryable, not exactly-once.

Reports use history already imported by existing Duels syncs. They do not force a
fresh sync. An immutable scheduled snapshot is retained even if later imports add
more historical games. Members without any completed sync are called out.
