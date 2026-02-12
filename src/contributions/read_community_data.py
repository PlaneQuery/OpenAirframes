#!/usr/bin/env python3
"""
Read and aggregate all community submission data.

Usage:
    python -m src.contributions.read_community_data
    python -m src.contributions.read_community_data --output merged.json
"""
import argparse
import json
import sys
from pathlib import Path


COMMUNITY_DIR = Path(__file__).parent.parent.parent / "community"


def read_all_submissions(community_dir: Path | None = None) -> list[dict]:
    """
    Read all JSON submissions from the community directory.
    
    Args:
        community_dir: Path to community directory. Uses default if None.
        
    Returns:
        List of all submission dictionaries
    """
    if community_dir is None:
        community_dir = COMMUNITY_DIR
    
    all_submissions = []
    
    # Search both root directory and date subdirectories (e.g., 2026-02-12/)
    for json_file in sorted(community_dir.glob("**/*.json")):
        try:
            with open(json_file) as f:
                data = json.load(f)
            
            # Normalize to list
            submissions = data if isinstance(data, list) else [data]
            
            # Add source file metadata
            for submission in submissions:
                submission["_source_file"] = json_file.name
            
            all_submissions.extend(submissions)
            
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: Failed to read {json_file}: {e}", file=sys.stderr)
    
    return all_submissions


def get_python_type_name(value) -> str:
    """Get a normalized type name for a value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def build_tag_type_registry(submissions: list[dict]) -> dict[str, str]:
    """
    Build a registry of tag names to their expected types from existing submissions.
    
    Args:
        submissions: List of existing submission dictionaries
        
    Returns:
        Dict mapping tag name to expected type (e.g., {"internet": "string", "year_built": "integer"})
    """
    tag_types = {}
    
    for submission in submissions:
        tags = submission.get("tags", {})
        if not isinstance(tags, dict):
            continue
        
        for key, value in tags.items():
            inferred_type = get_python_type_name(value)
            
            if key not in tag_types:
                tag_types[key] = inferred_type
            # If there's a conflict, keep the first type (it's already in use)
    
    return tag_types


def group_by_identifier(submissions: list[dict]) -> dict[str, list[dict]]:
    """
    Group submissions by their identifier (registration, transponder, or airframe ID).
    
    Returns:
        Dict mapping identifier to list of submissions for that identifier
    """
    grouped = {}
    
    for submission in submissions:
        # Determine identifier
        if "registration_number" in submission:
            key = f"reg:{submission['registration_number']}"
        elif "transponder_code_hex" in submission:
            key = f"icao:{submission['transponder_code_hex']}"
        elif "openairframes_id" in submission:
            key = f"id:{submission['openairframes_id']}"
        else:
            key = "_unknown"
        
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(submission)
    
    return grouped


def main():
    parser = argparse.ArgumentParser(description="Read community submission data")
    parser.add_argument("--output", "-o", help="Output file (default: stdout)")
    parser.add_argument("--group", action="store_true", help="Group by identifier")
    parser.add_argument("--stats", action="store_true", help="Print statistics only")
    
    args = parser.parse_args()
    
    submissions = read_all_submissions()
    
    if args.stats:
        grouped = group_by_identifier(submissions)
        contributors = set(s.get("contributor_uuid", "unknown") for s in submissions)
        
        print(f"Total submissions: {len(submissions)}")
        print(f"Unique identifiers: {len(grouped)}")
        print(f"Unique contributors: {len(contributors)}")
        return
    
    if args.group:
        result = group_by_identifier(submissions)
    else:
        result = submissions
    
    output = json.dumps(result, indent=2)
    
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Wrote {len(submissions)} submissions to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
