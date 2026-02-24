#!/usr/bin/env python3
"""
Generate a daily CSV of all community contributions.

Reads all JSON files from the community/ directory and outputs a sorted CSV
with creation_timestamp as the first column and contributor_name/contributor_uuid as the last columns.

Usage:
    python -m src.contributions.create_daily_community_release
"""
from datetime import datetime, timezone
from pathlib import Path
import json
import sys

import pandas as pd


COMMUNITY_DIR = Path(__file__).parent.parent.parent / "community"
OUT_ROOT = Path("data/openairframes")


def read_all_submissions(community_dir: Path) -> list[dict]:
    """Read all JSON submissions from the community directory."""
    all_submissions = []
    
    for json_file in sorted(community_dir.glob("**/*.json")):
        try:
            with open(json_file) as f:
                data = json.load(f)
            
            # Normalize to list
            submissions = data if isinstance(data, list) else [data]
            all_submissions.extend(submissions)
            
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: Failed to read {json_file}: {e}", file=sys.stderr)
    
    return all_submissions


def submissions_to_dataframe(submissions: list[dict]) -> pd.DataFrame:
    """
    Convert submissions to a DataFrame with proper column ordering.
    
    Column order:
    - creation_timestamp (first)
    - transponder_code_hex
    - registration_number  
    - openairframes_id
    - contributor_name
    - [other columns alphabetically]
    - contributor_uuid (last)
    """
    if not submissions:
        return pd.DataFrame()
    
    df = pd.DataFrame(submissions)
    
    # Ensure required columns exist
    required_cols = [
        "creation_timestamp",
        "transponder_code_hex",
        "registration_number",
        "openairframes_id",
        "contributor_name",
        "contributor_uuid",
    ]
    for col in required_cols:
        if col not in df.columns:
            df[col] = None
    
    # Sort by creation_timestamp ascending
    df = df.sort_values("creation_timestamp", ascending=True, na_position="last")
    
    # Reorder columns: specific order first, contributor_uuid last
    first_cols = [
        "creation_timestamp",
        "transponder_code_hex",
        "registration_number",
        "openairframes_id",
        "contributor_name",
    ]
    last_cols = ["contributor_uuid"]
    
    middle_cols = sorted([
        col for col in df.columns 
        if col not in first_cols and col not in last_cols
    ])
    
    ordered_cols = first_cols + middle_cols + last_cols
    df = df[ordered_cols]
    
    return df.reset_index(drop=True)


def main():
    """Generate the daily community contributions CSV."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    print(f"Reading community submissions from {COMMUNITY_DIR}")
    submissions = read_all_submissions(COMMUNITY_DIR)
    
    if not submissions:
        print("No community submissions found.")
        # Still create an empty CSV with headers
        df = pd.DataFrame(columns=[
            "creation_timestamp",
            "transponder_code_hex",
            "registration_number",
            "openairframes_id",
            "contributor_name",
            "tags",
            "contributor_uuid",
        ])
    else:
        print(f"Found {len(submissions)} total submissions")
        df = submissions_to_dataframe(submissions)
    
    # Determine date range for filename
    if not df.empty and df["creation_timestamp"].notna().any():
        # Get earliest timestamp for start date
        earliest = pd.to_datetime(df["creation_timestamp"]).min()
        start_date_str = earliest.strftime("%Y-%m-%d")
    else:
        start_date_str = date_str
    
    # Output
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    output_file = OUT_ROOT / f"openairframes_community_{start_date_str}_{date_str}.csv"
    
    df.to_csv(output_file, index=False)
    
    print(f"Saved: {output_file}")
    print(f"Total contributions: {len(df)}")
    
    return output_file


if __name__ == "__main__":
    main()
