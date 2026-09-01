## Never interpolate `${{ github.event.* }}` into a `run:` block

Actions substitutes `${{ }}` as raw text before the shell parses it, and issue bodies here are
public and unauthenticated. Pass untrusted values through `env:` and quote them.

A quoted heredoc delimiter does not save you: the body can *contain* the delimiter, close the
heredoc early, and execute every line after it. `validate-community-submission.yaml` had that shape.
Never fix this class of bug by escaping, sanitizing, or renaming the delimiter — move it to `env:`.

## Run everything from the repo root

`src/create_daily_faa_release.py` and `src/create_daily_tc_release.py` must be invoked as **scripts**
(`python src/create_daily_faa_release.py`). They use bare sibling imports, so `-m` raises
`ModuleNotFoundError`.
Everything under `src/adsb/` and `src/contributions/` is the opposite — `python -m`, package-relative.

Output paths are CWD-relative.

## Verification

There is no test framework, linter, or packaging config. **Do not add one unprompted**, and do not
treat "nothing broke" as verification.

The ADS-B path has no cheap end-to-end check — one day of input is tens of GB. Exercise
`compress_multi_icao_df` / `compress_df_polars` directly against a small hand-built Polars frame.

**Never `gh workflow run` to test a change.** Every dispatch pulls tens of GB and fans out over date
matrices. Reason about the YAML statically.

**Never commit generated data.** The product is a GitHub Release; jobs pass state as artifacts.

## ADS-B invariants

- `FINAL_COLUMN_ORDER` (`compress_adsb_to_aircraft_data.py`) is the only definition of the released
  column contract. `pl.concat` matches by **position** after `.select()`, and
  `get_latest_release.get_latest_aircraft_adsb_csv_df` parses released CSVs against the same order —
  so a forked copy corrupts the release with no error anywhere.
- `load_parquet_part()` deleting its source parquet is **deliberate**: the raw part is many GB and
  the runner would otherwise exhaust disk. Do not defer the delete to make reruns easier; that raises
  peak disk by the size of the part.
- A released row means "most informative observation for this ICAO on this UTC day" — non-empty
  fields not a subset of another row's, tie-broken by signature frequency. It is not a registry record.
- HTTP 404 is terminal in the release fetch. Restoring the retry makes the Dec-31 next-year-repo
  probe stall ~45 minutes on a repo that does not exist yet.

## Never edit or drop a `NOTICE` entry

Each entry is the permission that makes its asset redistributable; removing one removes the
permission. `NOTICE` is validated as a **required** release file and is listed in the
`create-release` sparse checkout — keep both. Transport Canada requires its two notices,
reproduction and value-added, to reach the consumer together.

`LICENSE` is MIT and covers **code only**. It makes no claim over released data, and neither may
you — an asset derived from a public-domain source is not itself public domain.

Before adding any registry, judge redistribution, not access, in this order:

1. **A public licence travels; a bilateral permission does not.** Written permission granted to
   another project or person is not a licence to this one. That alone disqualifies Taiwan, Estonia
   and Chile, whatever their commercial terms say.
2. **Non-commercial-only conditions are a second, independent bar** — they conflict with how these
   releases are consumed. Do not treat a source clearing this bar as cleared overall; rule 1 still
   applies. Taiwan is licensed OGDL v1.0, an open licence: its restriction is bilateral, not licence-borne.

CCARCS `ACTIVE_FLAG` does **not** mean "current owner": 1,932 currently-Registered marks carry only
`I` parties, and those rows are the `MAIL_RECIPIENT`. Prefer `A` parties where a mark has any, fall
back to all of them otherwise. Filtering on `A` alone publishes registered aircraft with no owner.

Owner mailing addresses **are** published, matching the `registrant_*` address the FAA asset already
carries — the two sources must not diverge on this. Addresses are per-party, so they come from the
single `MAIL_RECIPIENT == "Y"` row (exactly one per mark) and are never merged across co-owners; only
name, type, province and country are merged lists.

## Fork and upstream

`src/get_latest_release.py` pins `REPO = "PlaneQuery/openairframes"` on purpose: this fork reads
**upstream's** releases wherever it runs. Do not repoint it at `github.repository` without being asked.

Upstream develops on `develop` and PRs into `main`. The daily release **deletes the existing release
and tag** before recreating them.

## Community submissions are automation-owned

Merging to `community/**` or `schemas/**` force-pushes every open `community`-labeled PR branch back
onto main. Anything you hand-edit on such a branch is destroyed on the next merge.

- Never hand-author files in `community/` — the filename encodes `sha256(content)[:8]`, so an edit
  orphans the hash and duplicates on re-approval.
- Never invent or copy a `contributor_uuid`; it is derived from the GitHub user id.
- Do not reintroduce a hardcoded `"main"` or `v1` filename. Both are resolved at runtime now.

**A tag's JSON type is fixed by its first-ever submission and enforced forever** — emergent from
`build_tag_type_registry` + `validate_submission`, and written nowhere in the schema. Retyping or
renaming an existing tag breaks every future contributor, not just the current one.

Dropping a `community_submission.v2.schema.json` into `schemas/` promotes it atomically across every
reader and writer. That is a one-way door for contributors — only on explicit request.

## Conventions

- **Empty string, not null**, everywhere in released frames.
- Reuse `derive_from_faa_master_txt.normalize()` for `openairframes_id`; never re-derive the format.
- Python `3.14` for FAA/community/vendor jobs, `3.12` for ADS-B jobs (pyarrow pin + multiprocessing).
  Deliberate. Match the surrounding job; do not unify.

## References with no target — do not chase as regressions

| Reference | Missing |
|---|---|
| `process-historical-faa.yaml` | `src/get_historical_faa.py`, `scripts/concat_csvs.py` |
| `af-klm-fleet/package.json` → `npm run validate` | `af-klm-fleet/scripts/validate.js` |

`process-historical-faa.yaml` is dead, not stale — it also uses the disabled `::set-output`.
Repair-vs-delete is the owner's call; leave it alone unprompted.

## `af-klm-fleet/` and `community-routes/` are unwired

Nothing in CI touches either, and nothing consumes `community-routes/`. `af-klm-fleet/` is a vendored
project by a different author with its own license — its aircraft model is unrelated to
`schemas/community_submission.*`, so do not merge the two. Its `README.md` is generated by
`generate-readme.js`; hand edits are overwritten.

## Warts left standing — flag, do not silently fix

- `NUMBER_PARTS` is restated by the matrix and four hand-written upload steps in
  `adsb-to-aircraft-for-day.yaml`; changing the constant alone silently drops data. YAML cannot loop
  upload steps and one merged artifact would force every map job to download all parts, so any real
  fix is a restructure.
- `MAX_WORKERS = OS_CPU_COUNT if OS_CPU_COUNT > 4 else 1` collapses to a single worker on a ≤4-core
  runner, shrinking `files_per_batch` with it. Possibly intentional memory control — do not raise it
  without measuring peak RSS on the target runner.
- `update-community-prs.yaml` runs `regenerate_pr_schema || true` then force-pushes, so a
  regeneration failure ships anyway. Making it fatal leaves PRs un-rebased instead — a judgment call.
- `approve_submission.py` wraps its schema update in a bare `except Exception`, so a submission can
  merge without its new tags reaching the schema.

## Workflow authoring

The user's global GitHub Actions rules apply. Existing workflows violate most of them.
**Do not bulk-remediate** — bring only the file you were asked to touch up to standard, and surface
the rest in chat.

## External sources

`registry.faa.gov` and ADS-B Exchange are **required** — the release fails without them. Mictronics is
**tolerated**: it retries, then the job continues without it. adsb.lol may simply not have published a
given day, in which case the previous CSV is re-released rather than failing.

FAA refreshes at 05:30 UTC; the release cron fires at 06:00 UTC. That 30-minute margin is the reason
for the schedule.
