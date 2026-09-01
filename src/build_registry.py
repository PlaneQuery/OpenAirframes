"""Join the per-source registry CSVs into one union table.

Every source publishes its own `openairframes_<source>_{start}_{end}.csv` on its own thread.
This reads whatever landed, aligns them on the union of columns, and writes a single
`openairframes_registry_{start}_{end}.csv` discriminated by the `source` column.

Adding a registry means adding a source to the workflow matrix; nothing here changes.

Usage:
    python src/build_registry.py --input-dir artifacts/registry --date 2026-08-31
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import re
import sys

import pandas as pd

# Sources that are registries. Community and ADS-B are published separately: they are
# observations and contributions, not registration records, and do not share this schema.
FILENAME_RE = re.compile(r"openairframes_(?P<source>[a-z]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$")
EXCLUDED_SOURCES = {"community", "adsb", "registry"}

# Identifier columns lead the union so the table is usable without reading 70 headers.
LEADING_COLUMNS = [
    "download_date",
    "source",
    "transponder_code_hex",
    "registration_number",
    "openairframes_id",
]


def discover(input_dir: Path) -> list[tuple[str, str, str, Path]]:
    """Return (source, start, end, path) for each per-source registry CSV found."""
    found = []
    for path in sorted(input_dir.rglob("openairframes_*.csv")):
        match = FILENAME_RE.search(path.name)
        if not match:
            continue
        source = match.group("source")
        if source in EXCLUDED_SOURCES:
            continue
        found.append((source, match.group("start"), match.group("end"), path))
    return found


def build(input_dir: Path, date_str: str) -> tuple[pd.DataFrame, str, str]:
    parts = discover(input_dir)
    if not parts:
        raise SystemExit(f"No per-source registry CSVs found under {input_dir}")

    frames = []
    for source, _, _, path in parts:
        # keep_default_na=False so a literal "NA" survives the round trip unchanged.
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        if "source" not in df.columns:
            raise SystemExit(f"{path.name}: no source column; cannot discriminate rows")
        actual = set(df["source"].unique())
        if len(actual) != 1:
            raise SystemExit(f"{path.name}: expected one source value, found {sorted(actual)}")
        print(f"  {source}: {len(df)} rows, {len(df.columns)} columns from {path.name}")
        frames.append(df)

    columns = list(dict.fromkeys(c for df in frames for c in df.columns))
    ordered = [c for c in LEADING_COLUMNS if c in columns]
    ordered += [c for c in columns if c not in ordered]

    # reindex rather than concat directly: a source missing a column must yield an empty
    # cell, never a shifted row.
    df_union = pd.concat([df.reindex(columns=ordered) for df in frames], ignore_index=True)
    df_union = df_union.fillna("")

    start = min(p[1] for p in parts)
    end = max(p[2] for p in parts + [("", "", date_str, Path())])
    return df_union, start, end


def main() -> None:
    parser = argparse.ArgumentParser(description="Join per-source registry CSVs into one table")
    parser.add_argument("--input-dir", default="artifacts/registry", help="Directory to search")
    parser.add_argument("--output-dir", default="data/openairframes", help="Where to write")
    parser.add_argument("--date", help="Run date (YYYY-MM-DD, default: today UTC)")
    args = parser.parse_args()

    date_str = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    df, start, end = build(Path(args.input_dir), date_str)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"openairframes_registry_{start}_{end}.csv"
    df.to_csv(out_path, index=False)

    print(f"Wrote {out_path}: {len(df)} rows, {len(df.columns)} columns")
    print("  rows per source:")
    for source, count in df["source"].value_counts().items():
        print(f"    {source}: {count}")


if __name__ == "__main__":
    main()
