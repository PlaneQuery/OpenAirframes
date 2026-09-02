## Never interpolate `${{ github.event.* }}` or `${{ inputs.* }}` into a `run:` block

Pass them via `env:` and quote the shell variable. A quoted heredoc does not help — the body can
contain the delimiter and close it early. Never fix this by escaping or renaming the delimiter.

## Invocation

- `src/*.py` at the root of `src/` are scripts: `python src/create_daily_faa_release.py`. Bare
  sibling imports, so `-m` raises `ModuleNotFoundError`.
- `src/adsb/*`, `src/contributions/*` are packages: `python -m`.
- Run from the repo root; output paths are CWD-relative.

## Verification

- No test framework, linter, or packaging config. Do not add one unprompted.
- Never `gh workflow run` to test a change — every dispatch pulls tens of GB.
- Never commit generated data. The product is a GitHub Release; jobs pass state as artifacts.
- ADS-B has no cheap end-to-end check. Exercise `compress_multi_icao_df` on a hand-built frame.

## Release invariants

- `FINAL_COLUMN_ORDER` (`compress_adsb_to_aircraft_data.py`) is the only definition of the ADS-B
  column contract. `pl.concat` matches by position after `.select()`; a forked copy corrupts the
  release with no error.
- Empty string, never null, in every released frame.
- `openairframes_id` = `normalize(manufacturer)|normalize(model)|normalize(serial)`. Reuse
  `derive_from_faa_master_txt.normalize()`.
- Each source's daily build reads its own previous release asset and appends. Falling back to a
  single-day rebuild on anything but `FileNotFoundError` republishes one day as the whole dataset,
  which the next run then reads back as its base. Keep the fallback narrow.
- Python `3.14` for FAA/community/vendor jobs, `3.12` for ADS-B. Match the surrounding job.

## Registry sources

- Judge **redistribution**, not access. A public licence travels to this project; a bilateral
  permission granted to another project does not — that alone disqualifies Taiwan, Estonia, Chile.
  Non-commercial-only terms are a separate, independent bar.
- `NOTICE` carries the terms that make each asset redistributable and is a required release file.
  Never edit or drop an entry. Transport Canada requires both its notices together.
- `LICENSE` is MIT and covers code only. Claim nothing about released data.
- Owner/registrant mailing addresses are published for every registry. FAA and TC must not diverge.
- CCARCS `ACTIVE_FLAG` is not "current owner": 1,932 Registered marks carry only `I` parties, and
  those rows are the `MAIL_RECIPIENT`. Prefer `A`, fall back to all.
- CCARCS addresses come from the single `MAIL_RECIPIENT == "Y"` row, never merged across co-owners.

## ADS-B

- `load_parquet_part()` deleting its source parquet is deliberate — disk pressure. Do not defer it.
- A released row is the most informative observation for that ICAO on that UTC day, not a registry
  record.
- HTTP 404 is terminal in the release fetch; restoring the retry stalls the Dec-31 probe ~45 min.

## Community submissions are automation-owned

- Merging `community/**` or `schemas/**` force-pushes every open `community` PR branch onto main.
  Hand edits there are destroyed.
- Never hand-author `community/` files — the filename encodes `sha256(content)[:8]`.
- A tag's JSON type is fixed by its first submission and enforced forever. Emergent from
  `build_tag_type_registry` + `validate_submission`; written nowhere in the schema.
- Adding `community_submission.v2.schema.json` promotes it atomically across every reader and
  writer. One-way door — only on request.

## Fork

`get_latest_release.REPO` pins upstream `PlaneQuery/openairframes` on purpose. Do not repoint it.
Upstream develops on `develop`. The daily release deletes the existing release and tag first.

## Do not chase

- `process-historical-faa.yaml` is dead: missing `src/get_historical_faa.py`,
  `scripts/concat_csvs.py`, and uses the disabled `::set-output`.
- `af-klm-fleet/package.json` → `npm run validate` has no `scripts/validate.js`.
- `af-klm-fleet/` and `community-routes/` are unwired; nothing in CI touches them.
  `af-klm-fleet/README.md` is generated.

## Flag, do not silently fix

- `NUMBER_PARTS` is restated by the matrix and four upload steps in `adsb-to-aircraft-for-day.yaml`.
- `MAX_WORKERS = ... if OS_CPU_COUNT > 4 else 1` collapses to one worker on a ≤4-core runner.
- `update-community-prs.yaml` runs `regenerate_pr_schema || true`, then force-pushes.
- `approve_submission.py` wraps its schema update in a bare `except Exception`.
- Existing workflows violate the global GHA rules. Fix only the file you were asked to touch.
