#!/usr/bin/env python3
"""
Parse TheAirTraffic Database CSV and produce community_submission.v1 JSON.

Source: "TheAirTraffic Database - Aircraft 2.csv"
Output: community/YYYY-MM-DD/theairtraffic_<date>_<hash>.json

Categories in the spreadsheet columns (paired: name, registrations, separator):
  Col  1-3:  Business
  Col  4-6:  Government
  Col  7-9:  People
  Col 10-12: Sports
  Col 13-15: Celebrity
  Col 16-18: State Govt./Law
  Col 19-21: Other
  Col 22-24: Test Aircraft
  Col 25-27: YouTubers
  Col 28-30: Formula 1 VIP's
  Col 31-33: Active GII's and GIII's  (test/demo aircraft)
  Col 34-37: Russia & Ukraine          (extra col for old/new)
  Col 38-40: Helicopters & Blimps
  Col 41-43: Unique Reg's
  Col 44-46: Saudi & UAE
  Col 47-49: Schools
  Col 50-52: Special Charter
  Col 53-55: Unknown Owners
  Col 56-59: Frequent Flyers           (extra cols: name, aircraft, logged, hours)
"""

import csv
import json
import hashlib
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ── Category mapping ────────────────────────────────────────────────────────
# Each entry: (name_col, reg_col, owner_category_tags)
# owner_category_tags is a dict of tag keys to add beyond "owner"
CATEGORY_COLUMNS = [
    # (name_col, reg_col, {tag_key: tag_value, ...})
    (1,  2,  {"owner_category_0": "business"}),
    (4,  5,  {"owner_category_0": "government"}),
    (7,  8,  {"owner_category_0": "celebrity"}),
    (10, 11, {"owner_category_0": "sports"}),
    (13, 14, {"owner_category_0": "celebrity"}),
    (16, 17, {"owner_category_0": "government", "owner_category_1": "law_enforcement"}),
    (19, 20, {"owner_category_0": "other"}),
    (22, 23, {"owner_category_0": "test_aircraft"}),
    (25, 26, {"owner_category_0": "youtuber", "owner_category_1": "celebrity"}),
    (28, 29, {"owner_category_0": "celebrity", "owner_category_1": "motorsport"}),
    (31, 32, {"owner_category_0": "test_aircraft"}),
    # Russia & Ukraine: col 34=name, col 35 or 36 may have reg
    (34, 35, {"owner_category_0": "russia_ukraine"}),
    (38, 39, {"owner_category_0": "celebrity", "category": "helicopter_or_blimp"}),
    (41, 42, {"owner_category_0": "other"}),
    (44, 45, {"owner_category_0": "government", "owner_category_1": "royal_family"}),
    (47, 48, {"owner_category_0": "education"}),
    (50, 51, {"owner_category_0": "charter"}),
    (53, 54, {"owner_category_0": "unknown"}),
    (56, 57, {"owner_category_0": "celebrity"}),   # Frequent Flyers name col, aircraft col
]

# First data row index (0-based) in the CSV
DATA_START_ROW = 4

# ── Contributor info ────────────────────────────────────────────────────────
CONTRIBUTOR_NAME = "TheAirTraffic"
# Deterministic UUID v5 from contributor name
CONTRIBUTOR_UUID = str(uuid.uuid5(uuid.NAMESPACE_URL, "https://theairtraffic.com"))

# Citation
CITATION = "https://docs.google.com/spreadsheets/d/1JHhfJBnJPNBA6TgiSHjkXFkHBdVTTz_nXxaUDRWcHpk"


def looks_like_military_serial(reg: str) -> bool:
    """
    Detect military-style serials like 92-9000, 82-8000, 98-0001
    or pure numeric IDs like 929000, 828000, 980001.
    These aren't standard civil registrations; use openairframes_id.
    """
    # Pattern: NN-NNNN
    if re.match(r'^\d{2}-\d{4}$', reg):
        return True
    # Pure 6-digit numbers (likely ICAO hex or military mode-S)
    if re.match(r'^\d{6}$', reg):
        return True
    # Short numeric-only (1-5 digits) like "01", "02", "676"
    if re.match(r'^\d{1,5}$', reg):
        return True
    return False


def normalize_reg(raw: str) -> str:
    """Clean up a registration string."""
    reg = raw.strip().rstrip(',').strip()
    # Remove carriage returns and other whitespace
    reg = reg.replace('\r', '').replace('\n', '').strip()
    return reg


def parse_regs(cell_value: str) -> list[str]:
    """
    Parse a cell that may contain one or many registrations,
    separated by commas, possibly wrapped in quotes.
    """
    if not cell_value or not cell_value.strip():
        return []

    # Some cells have ADS-B exchange URLs – skip those
    if 'globe.adsbexchange.com' in cell_value:
        return []
    if cell_value.strip() in ('.', ',', ''):
        return []

    results = []
    # Split on comma
    parts = cell_value.split(',')
    for part in parts:
        reg = normalize_reg(part)
        if not reg:
            continue
        # Skip URLs, section labels, etc.
        if reg.startswith('http') or reg.startswith('Link') or reg == 'Section 1':
            continue
        # Skip if it's just whitespace or dots
        if reg in ('.', '..', '...'):
            continue
        results.append(reg)
    return results


def make_submission(
    reg: str,
    owner: str,
    category_tags: dict[str, str],
) -> dict:
    """Build a single community_submission.v1 object."""

    entry: dict = {}

    # Decide identifier field
    if looks_like_military_serial(reg):
        entry["openairframes_id"] = reg
    else:
        entry["registration_number"] = reg

    # Tags
    tags: dict = {
        "citation_0": CITATION,
    }
    if owner:
        tags["owner"] = owner.strip()
    tags.update(category_tags)
    entry["tags"] = tags

    return entry


def main():
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "/Users/jonahgoode/Downloads/TheAirTraffic Database - Aircraft 2.csv"
    )

    if not csv_path.exists():
        print(f"ERROR: CSV not found at {csv_path}", file=sys.stderr)
        sys.exit(1)

    # Read CSV
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        rows = list(reader)

    print(f"Read {len(rows)} rows from {csv_path.name}")

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    submissions: list[dict] = []
    seen: set[tuple] = set()  # (reg, owner) dedup

    for row_idx in range(DATA_START_ROW, len(rows)):
        row = rows[row_idx]
        if len(row) < 3:
            continue

        for name_col, reg_col, cat_tags in CATEGORY_COLUMNS:
            if reg_col >= len(row) or name_col >= len(row):
                continue

            owner_raw = row[name_col].strip().rstrip(',').strip()
            reg_raw = row[reg_col]

            # Clean owner name
            owner = owner_raw.replace('\r', '').replace('\n', '').strip()
            if not owner or owner in ('.', ',', 'Section 1'):
                continue
            # Skip header-like values
            if owner.startswith('http') or owner.startswith('Link '):
                continue

            regs = parse_regs(reg_raw)
            if not regs:
                # For Russia & Ukraine, try the next column too (col 35 might have old reg, col 36 new)
                if name_col == 34 and reg_col + 1 < len(row):
                    regs = parse_regs(row[reg_col + 1])

            for reg in regs:
                key = (reg, owner)
                if key in seen:
                    continue
                seen.add(key)
                submissions.append(make_submission(reg, owner, cat_tags))

    print(f"Generated {len(submissions)} submissions")

    # Write output
    proj_root = Path(__file__).resolve().parent.parent
    out_dir = proj_root / "community" / date_str
    out_dir.mkdir(parents=True, exist_ok=True)

    out_file = out_dir / f"theairtraffic_{date_str}.json"

    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(submissions, f, indent=2, ensure_ascii=False)

    print(f"Written to {out_file}")
    print(f"Sample entry:\n{json.dumps(submissions[0], indent=2)}")

    # Quick stats
    cats = {}
    for s in submissions:
        c = s['tags'].get('owner_category_0', 'NONE')
        cats[c] = cats.get(c, 0) + 1
    print("\nCategory breakdown:")
    for c, n in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"  {c}: {n}")


if __name__ == "__main__":
    main()
