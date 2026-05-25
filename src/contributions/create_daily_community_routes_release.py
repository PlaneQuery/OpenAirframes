#!/usr/bin/env python3
"""Generate a daily CSV of all approved community route submissions."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
import sys

from .routes import COMMUNITY_ROUTES_DIR, parse_metadata_header, parse_routes_text


OUT_ROOT = Path("data/openairframes")

OUTPUT_COLUMNS = [
    "creation_timestamp",
    "callsign",
    "route",
    "origin",
    "destination",
    "waypoints",
    "source_issue",
    "contributor_name",
    "source_file",
    "contributor_uuid",
]


def read_all_route_rows(community_routes_dir: Path = COMMUNITY_ROUTES_DIR) -> list[dict]:
    """Read all route submission text files into CSV-ready rows."""
    rows: list[dict] = []

    for route_file in sorted(community_routes_dir.glob("**/*.txt")):
        try:
            text = route_file.read_text()
        except OSError as e:
            print(f"Warning: Failed to read {route_file}: {e}", file=sys.stderr)
            continue

        metadata = parse_metadata_header(text)
        routes, errors = parse_routes_text(text)
        for error in errors:
            print(f"Warning: {route_file}: {error}", file=sys.stderr)

        for route in routes:
            route_codes = list(route.route)
            rows.append({
                "creation_timestamp": metadata.get("creation_timestamp"),
                "callsign": route.callsign,
                "route": " ".join(route_codes),
                "origin": route_codes[0],
                "destination": route_codes[-1],
                "waypoints": " ".join(route_codes[1:-1]),
                "source_issue": metadata.get("source_issue"),
                "contributor_name": metadata.get("contributor_name"),
                "source_file": str(route_file.relative_to(community_routes_dir.parent)),
                "contributor_uuid": metadata.get("contributor_uuid"),
            })

    return rows


def sort_route_rows(rows: list[dict]) -> list[dict]:
    """Sort route rows and ensure stable columns."""
    normalized_rows = []
    for row in rows:
        normalized_rows.append({col: row.get(col) for col in OUTPUT_COLUMNS})

    return sorted(
        normalized_rows,
        key=lambda row: (
            row.get("creation_timestamp") or "",
            row.get("callsign") or "",
            row.get("route") or "",
        ),
    )


def get_start_date(rows: list[dict], fallback_date: str) -> str:
    """Get the earliest creation date from route metadata."""
    dates = []
    for row in rows:
        timestamp = row.get("creation_timestamp")
        if not timestamp:
            continue
        dates.append(timestamp[:10])
    return min(dates) if dates else fallback_date


def main() -> Path:
    """Generate the daily community routes CSV."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"Reading community route submissions from {COMMUNITY_ROUTES_DIR}")
    rows = read_all_route_rows()
    print(f"Found {len(rows)} total route rows")

    rows = sort_route_rows(rows)
    start_date_str = get_start_date(rows, date_str)

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    output_file = OUT_ROOT / f"openairframes_community_routes_{start_date_str}_{date_str}.csv"

    with output_file.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved: {output_file}")
    print(f"Total community routes: {len(rows)}")
    return output_file


if __name__ == "__main__":
    main()
