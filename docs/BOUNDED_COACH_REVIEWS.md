# Bounded decision review: first offline validation

This patch is based on main commit `01411b4` and assumes the packaged rules/updater changes are already installed. No database migration is needed. No paid model calls or production changes were made while developing it.

## Behavior

- The coach reviews a selected turn, not the whole game. `/coach` accepts an optional `turn` argument using the replay's `gameplay_turn` numbering. Without it, the first recorded player turn is used, explicitly not ranked by importance. The offline preview accepts one or two `--turn` arguments; Discord currently accepts one.
- Whole selected turns, their original compacted contexts, and full referenced card facts are retained. Omitted history and snapshot timing must not be inferred. Recorded player action counts across the full replay are calculated in Python and labeled as counts, not quality judgments.
- A first-pass lexical retriever selects up to two complete rule pages based on selected card text and full-name matches. No matches stops the request. This is NOT certified retrieval coverage; relevant exceptions may be missing. The model is instructed to abstain where evidence is insufficient. Retrieval quality on the actual production replay has not been evaluated yet.
- The full feature dump, duplicated grounding configuration and remaining reference pages are omitted from the model request. Stored catalog/reference provenance and the original input digest remain available in the analysis record. Usage now includes selected turns, reference IDs, recorded counts and the budget calculation.
- Before sending, a conservative UTF-8 byte-based input token bound counts the whole serialized API request plus framing allowance. At reviewed standard GPT-5.4 rates, the input bound plus the full 1,200-token output allowance must fit $0.05. Unknown models or oversize requests stop before the network call. Prices are pinned to the September 19, 2026 review; update them if provider pricing changes. This is a conservative application estimate, not a contractual provider billing guarantee or an account-wide spending limit.
- The application does not silently trim a large decision to meet the budget. A busy turn may be blocked. The free preview will show this; do not raise the limit just to get through the first test.
- New coaching jobs have one attempt. The API adapter has one attempt. Coaching errors are treated as permanent so automatic error retries do not repeatedly spend money. Jobs queued before this deployment retain their old attempt limits, and a manually submitted new request can still incur another charge.
- Generated findings must be inference, and cannot escape this by calling themselves replay observations. Confidence percentages and fact labels are removed from newly rendered reports. The legacy non-null database confidence field is stored as 0 with `confidence_status=unscored`; this is not a probability. Existing saved report text is not rewritten.
- Exact card text containing “until the start of your next turn” produces an explicit duration annotation. If model prose then combines next-turn language with lore advice, the report is withheld for human review. This intentionally conservative guard catches the known Alice failure and may reject correct prose too. It does NOT validate all temporal effects or establish general rules correctness. A rejected model response has already used tokens.

## Apply locally

Keep new Discord coaching requests disabled while testing. In your local repository:

```bash
git switch -c coach/bounded-decision-reviews
git apply --check /path/to/bounded-coach.patch
git apply /path/to/bounded-coach.patch
python -m pip install -e '.[dev]'
python -m pytest -q tests/unit
git diff --check
```

Commit, push and use your normal PR/CI deployment flow. Stop if the patch check fails; don't force it onto conflicting source. The local suite passed 224 tests and two subtests. Live PostgreSQL and deployed Discord validation remain to be done.

The default model is now `gpt-5.4`, one of the explicitly priced models. If Railway already has `OPENAI_COACH_MODEL`, make sure it is `gpt-5.4` for previewing. Keep `LORCANA_COACH_RULES_BUNDLE` unset to use packaged references.

Before eventually re-enabling the bot, set BOTH worker and bot to:

```text
LORCANA_COACH_ANALYZER_GENERATION=bounded-v5-2026-09-19
```

Do not enable new paid requests yet. A `/coach` request after enabling calls the model if the budget check passes; preview is the separate free command below.

## Next step: run in the Railway worker shell

After deploying the patch, paste this complete command into the WORKER shell:

```bash
python -m lorcana.coach.preview \
  --game-id 019e11b9-c805-7f74-aea3-51a0d870157b \
  --connection-id 2a80b1a9-886d-4ac3-a4fa-8314985b4d61 \
  --turn 4
```

This reads the existing database and packaged references. It creates no jobs and makes no OpenAI request; it works without an API key. It prints the selected card IDs, rule page IDs, duration annotations, recorded statistics and estimated budget. Share the output to assess size and source selection before any paid trial. `allowed: false` means the paid path would stop without sending.

## Remaining quality work

A production replay preview is required to determine if this whole-turn representation fits the bound. Further compaction must preserve the decision state, not merely shorten JSON. Before calling the model again, review retrieved passages and surrounding exceptions, verify the actual Alice catalog text and selected actions, and build more human-labeled interaction cases. The current suite checks selection integrity, no-call budget rejection, citation scope, labels and the known Alice guard; it does not certify strategic coaching quality.

This remains a partial review tool. Automatic identification of high-value decision points, calibrated retrieval of dependent rule sections, a complete temporal rules engine, team spending quotas and durable private report navigation are not implemented by this patch.
