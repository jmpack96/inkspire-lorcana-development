# Coach grounding: first implementation

This change addresses the observed Duels `3-223` printing mismatch and adds official-rule reference checks before paid analysis. It requires no database migration. It is not a full game-rules engine or a certification that model advice is correct.

## What changes

- Exact card IDs must agree with observed full names when available.
- Reviewed aliases retain the Duels ID in replay evidence and resolve to a catalog gameplay entry. The initial reviewed alias is Piglet - Pooh Pirate Captain (`3-223`). Lorcast currently returns its standard printing as `3-16`.
- Unknown IDs get candidate suggestions, not automatic name-based mappings. Conflicting candidate gameplay data blocks resolution. To add a verified printing, add an entry to `REVIEWED_ALIASES` in `src/lorcana/catalog/resolver.py`, record the review source, and add a regression case. Do not use base character names without subtitles.
- The snapshot ID, resolver version, mapping decisions, and rules reference hash/metadata are recorded with the analysis. Original replays and catalog snapshots remain unchanged.
- Lorcast single-ink fallback is corrected (`inks: null` falls back to `ink`). A fresh catalog import is needed to repair existing empty color fields.
- Static catalog combat statistics and replay board statistics are exposed to the analyzer. Missing required statistics or colors block analysis.
- Official rules are imported into a checksum-pinned local JSON bundle. The import verifies the PDF's version and effective date, preserves all page text, and refuses to overwrite an existing output file. Citations identify document version and PDF page.
- OpenAI analysis requires a rules bundle covering the game's recorded start date and resolved, complete card facts. It does not silently apply July rules to earlier games.
- Findings declare their basis and card/rule citations. Unknown citation IDs are rejected. Rules interpretations require both kinds of citation and must be labeled inference. Report citations link to the source PDF page.
- Prompt generation advances to `lorcana_coach_v2_grounded`; existing reports remain historical records.

## Apply the patch

Work in a local clone of `jmpack96/inkspire-lorcana-development`, not a Railway container. The patch is based on commit `5010a3bb115a58a5e8dd0733ef3af8bd43edddb4`.

```bash
git switch -c coach/grounded-card-and-rules-references
git apply --check /path/to/coach-grounding.patch
git apply /path/to/coach-grounding.patch
python -m pip install -e '.[dev]'
python -m pytest -q tests/unit
git diff --check
```

Review and commit the files, then push your branch and use your normal GitHub review/deployment flow. If `git apply --check` fails, stop and reconcile the newer source instead of overwriting files. No production configuration or data has been changed by preparing this patch.

## Prepare the rules reference after deployment

Official landing page: https://www.disneylorcana.com/en-US/resources

The English Comprehensive Rules linked there were version 2.2.0, effective July 9, 2026, when checked on September 19, 2026. A current rules document alone does not establish historical errata or set-ruling coverage.

In the worker shell, download that exact document to the persistent `/data` volume and check its bytes:

```bash
python - <<'PY'
import hashlib
from pathlib import Path
import requests
url = 'https://files.disneylorcana.com/Comprehensive-Rules_2.2.0-EN.pdf'
response = requests.get(url, timeout=60)
response.raise_for_status()
expected = '5ffa31172fcaae2cbdbf127aebdd54987f01a4e72008812c96556c29d0942d8f'
if hashlib.sha256(response.content).hexdigest() != expected:
    raise SystemExit('Official PDF bytes changed: review the document before importing.')
path = Path('/data/lorcana-rules-2.2.0.pdf')
with path.open('xb') as handle:
    handle.write(response.content)
print(path)
PY

python -m lorcana.coach.rules \
  --pdf /data/lorcana-rules-2.2.0.pdf \
  --version 2.2.0 \
  --effective-from 2026-07-09 \
  --verified-through 2026-09-19 \
  --output /data/lorcana-rules-2.2.0-reviewed-2026-09-19.json
```

`verified-through` is deliberately an operator-reviewed cutoff, not a prediction that the rules will remain unchanged. Recheck official rules, errata, and set notes before extending it. Retain old bundles. Replays outside the loaded date range are blocked until an applicable reference is configured; automatic multi-version selection is not included yet.

Set on the worker:

```text
LORCANA_COACH_RULES_BUNDLE=/data/lorcana-rules-2.2.0-reviewed-2026-09-19.json
```

When changing references or reviewed aliases, update `LORCANA_COACH_ANALYZER_GENERATION` on both worker and bot so the job queue does not reuse an older completed request. For this initial version, use:

```text
LORCANA_COACH_ANALYZER_GENERATION=grounded-v2-rules-2.2.0-reviewed-2026-09-19
```

The existing OpenAI analyzer/model/key configuration is still required when you enable analysis. Keep the API key in Railway secrets. This patch does not choose a model or make paid API calls.

Refresh the catalog once with the corrected importer:

```bash
lorcana catalog-enqueue-refresh --generation grounded-v2-colors
```

Use a new snapshot after that job succeeds. No replay redownload is needed. Test one game with a known date in the supported range before onboarding teammates.

## Validation and remaining work

206 unit tests and two subtests passed locally, including reviewed aliases, unknown-printing rejection, subtitle conflicts, ambiguous gameplay facts, missing card attributes, rule-date boundaries, tampered bundles, invented citation rejection, and no model call without references. The official PDF was downloaded, its cover/version/effective date checked, and all 55 pages extracted successfully. No paid API call or production database mutation was performed. Live PostgreSQL integration and deployment remain to be run in the project's CI/Railway environment.

Important limits:

- Valid citations prove source existence, not relevance or correct interpretation. The model may still misclassify a claim, overlook an exception, or introduce unsupported prose. Human review remains necessary.
- Only the Comprehensive Rules reference is loaded in this slice. Official set notes, errata, and historical versions need separate ingestion, conflict resolution, and coverage tests. The prompt instructs omission where these are required but absent; this is not mechanically enforceable yet.
- No deterministic legality engine has been added. Resource costs, ability timing, continuous effects, alternative costs, and challenge legality need explicit, narrowly scoped validators with known-state prerequisites and `unknown` outcomes.
- Rules are currently sent as the full document (about 190,000 characters), which increases model input cost. Retrieval can replace this later only with tests ensuring necessary exceptions are included.
- Reviewed aliases live in source control for this small team. Unknown printings require review; no automatic guessing is used.
- Replay parsing warnings and hidden information can still limit analysis quality. Passing this suite is not proof of strategic quality; a human-labeled replay evaluation set is the next quality gate.
