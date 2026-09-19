# Coach card and rules grounding

The coach resolves reviewed alternate printings, requires complete card facts, and cites official rules. It is not a deterministic legality engine. No database migration is needed.

## Packaged references

`src/lorcana/coach/resources/rules-current.json` is committed with the application and included in its installed Python package. `load_bundle()` loads this resource independently of the working directory. Docker validates it during the build. No runtime download or manually created container file is required.

The bundle contains 182 PDF pages from seven official English documents linked on [Disney Lorcana's resources page](https://www.disneylorcana.com/en-US/resources), checked September 19, 2026:

- Comprehensive Rules 2.2.0, effective July 9, 2026 (55 pages).
- Tournament Rules, effective July 14, 2026 (29 pages). The resources page update date is July 23; the effective date comes from the PDF.
- Fabled set release notes (25 pages).
- Whispers in the Well set release notes (16 pages).
- Winterspell set release notes (7 pages).
- Wilds Unknown set release notes (20 pages).
- Attack of the Vine! set release notes (30 pages).

Each document has its official source URL, source PDF SHA-256, title, kind, and review date. Citations identify the document and PDF page. The complete extracted bundle has a checksum. Fabled describes itself as the first set release notes; this bundle does not claim a separate guide exists for every earlier set. Complete errata and historical rules coverage are not claimed. Copyright remains with the source owners.

## Historical games

Replays remain reviewable before July 9, after the last review date, and when their date is unknown. The reference window now records provenance rather than blocking the game.

Every grounded report displays a current-reference notice, including reports with no findings. Rules-dependent advice is framed as practice under the bundled references. The model is explicitly instructed not to call an old play illegal, treat a later rule change as a player mistake, or assume current catalog wording existed on the replay date. Predating the comprehensive rules, postdating the last review, and unknown dates receive explicit notices. Even a date inside the reference window is not a certification of historical legality.

Set guides can describe superseded rules. The prompt requires consideration of that context and omission of claims when source conflicts cannot be resolved. Citation checks establish that references exist, not that the model used them correctly. Historical applicability and semantic conflict resolution are not mechanically verified.

## Deploy this update

If the previous packaged-rules patch has NOT been applied, apply `full-update.patch` to a local clone based on main commit `6fcdefd` (which includes the original grounding change):

```bash
git switch -c coach/packaged-rules-and-set-guides
git apply --check /path/to/full-update.patch
git apply /path/to/full-update.patch
python -m pip install -e '.[dev]'
python -m pytest -q tests/unit
git diff --check
```

If you already applied the previous packaged-rules patch, apply `incremental-update.patch` instead. Do not apply both patches.

Commit and push the branch, open a PR, and pass the PostgreSQL CI gate before merging/deploying. If patch checking fails, reconcile changes rather than forcing the patch.

On Railway, REMOVE `LORCANA_COACH_RULES_BUNDLE` from the worker (and any shared/service variables). Removing it selects the packaged default. An explicit override is still honored and fails clearly when missing or corrupt; it never silently falls back. Do not point it to the old `/data` or `/app/data` file.

Set this on BOTH worker and Discord bot to avoid reusing old completed queue requests:

```text
LORCANA_COACH_ANALYZER_GENERATION=references-96e87dbe45da7c69
```

The model prompt version is `lorcana_coach_v4_tournament_references`. Existing OpenAI model/analyzer/key settings still apply. This update does not enable analysis or make paid calls.

After deployment, verify the actual configuration in the worker:

```bash
python - <<'PY'
from lorcana.config import Settings
from lorcana.coach.rules import load_bundle, for_game
settings = Settings.from_env()
bundle = load_bundle(settings.coach_rules_bundle)
rules = for_game(bundle, '2026-05-10T11:50:48.595000+00:00')
print('Documents:', len(bundle.get('documents', {})))
print('Pages:', len(bundle['citations']))
print('Status:', rules['status'])
print('Date coverage:', rules['date_coverage'])
print('Notice:', rules['review_notice'])
PY
```

Expected: seven documents, 182 pages, available, before_reference. Then repeat the actual replay evidence diagnostic using `load_bundle(resources.settings.coach_rules_bundle)`; no hardcoded path is needed.

## Card identity checks

Exact IDs must agree with observed full names. Reviewed aliases retain replay IDs while supplying canonical gameplay facts. Piglet - Pooh Pirate Captain `3-223` resolves to `3-16`. Unknown printings get candidate suggestions but are not automatically mapped. Conflicting gameplay facts block resolution. Add verified printings in `REVIEWED_ALIASES` with review provenance and a regression case.

Incomplete card statistics or ink colors still block model analysis. If an older catalog has empty single-ink colors, refresh it with the corrected importer and use the new snapshot. No replay redownload is necessary. The existing audit on snapshot `650da9cd-b528-479d-bb30-c11050ace6fd` passed for the affected Piglet replay.

## Updating references

Run these commands in your LOCAL repository, not an ephemeral Railway shell. Install the project dependencies first (`python -m pip install -e '.[dev]'`).

Check for changes without writing a file:

```bash
python -m lorcana.coach.reference_refresh
```

The updater reads the official resources page, discovers English comprehensive rules, tournament rules and set-note PDFs, downloads them and compares their SHA-256 hashes and URLs against the packaged bundle. It catches new set notes, new URLs, and changed bytes at the same URL. It prints new, changed, unchanged and no-longer-listed documents. If the page layout is unrecognized, required categories are absent, or a download fails, it raises an error rather than reporting everything as current.

Prepare an updated bundle:

```bash
python -m lorcana.coach.reference_refresh --output rules-next.json
```

This never overwrites an existing output and does not activate anything. It prints a suggested analyzer generation derived from the bundle hash. `--baseline PATH` selects a different baseline. `--checked-on YYYY-MM-DD` overrides the source check date; the default is today's date and future dates are rejected.

Review the printed changes and extracted text. The effective dates for comprehensive and tournament rules are taken from their PDF covers, not the landing-page update dates. An unrecognized cover format stops the build for review. Set notes have no invented effective date. Removed set guides are retained with `currently_listed: false`, keeping older card rulings available and making their status visible. Unchanged PDFs retain the previous extraction to avoid incidental font-extraction differences.

To activate the reviewed update:

```bash
cp rules-next.json src/lorcana/coach/resources/rules-current.json
python -m pytest -q tests/unit
```

Commit the bundle and deploy through the normal PR workflow. Update `LORCANA_COACH_ANALYZER_GENERATION` on both worker and Discord bot to the suggested value so old completed requests are not reused. Git preserves the prior bundle for rollback. A reference check date records source freshness, not proof of historical applicability or correct model interpretation.

This is an on-demand updater. No scheduled job, automatic PR, or live document replacement is enabled. Activation stays tied to a reviewed deployment so sources cannot silently change underneath saved reports.

## Tournament reference scope

Tournament rules are available as a separate document kind with their own citations and effective date. The prompt distinguishes gameplay rules from tournament procedures. It requires tournament sources for claims about match procedure, takebacks, concessions/draws, deck legality or time limits, and does not assume that a Duels game was a sanctioned event. Missing format, event level, clock or agreement context means conditional guidance only. Penalties and judge remedies require the applicable correction policy, which is not bundled here. These are prompt-level safeguards, not a complete tournament policy engine.

## Validation and limits

216 unit tests and two subtests passed, including package loading from another directory, missing override errors, integrity checks, historical-date notices, document-specific report links, reviewed aliases, and citation validation. The installed wheel is checked separately for the packaged resource. Live PostgreSQL CI, Railway deployment and real model output still need validation.

All extracted reference pages are sent to the model (about 350,000 characters), increasing input cost. No retrieval or scheduled automatic activation has been added. Human review is still needed for strategic quality, source interpretation, hidden information, parser limitations, historical card wording and unsupported claims. Those limits do not invalidate the replay's recorded observations.
