#!/usr/bin/env python3
"""
Regenerate schema for a PR branch after main has been merged in.
This script looks at the submission files in this branch and generates
an updated schema version if new tags were introduced.

Usage: python -m src.contributions.regenerate_pr_schema
"""

import json
import sys
from pathlib import Path

# Add parent to path for imports when running as script
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.contributions.read_community_data import read_all_submissions, build_tag_type_registry
from src.contributions.update_schema import (
    get_existing_tag_definitions,
    check_for_new_tags,
    generate_new_schema,
)
from src.contributions.schema import get_latest_schema_version, load_schema, SCHEMAS_DIR


def main():
    """Main entry point."""
    # Get current schema version and load it
    current_version = get_latest_schema_version()
    current_schema = load_schema()
    
    # Get existing tag definitions from schema
    existing_tags = get_existing_tag_definitions(current_schema)
    
    # Read all submissions (including ones from this PR branch)
    submissions = read_all_submissions()
    
    if not submissions:
        print("No submissions found")
        return
    
    # Build tag registry from all submissions
    tag_registry = build_tag_type_registry(submissions)
    
    # Check for new tags not in the current schema
    new_tags = check_for_new_tags(tag_registry, current_schema)
    
    if new_tags:
        # Generate new schema version
        new_version = current_version + 1
        print(f"Found new tags: {new_tags}")
        print(f"Generating schema v{new_version}")
        
        # Generate new schema with updated tag definitions
        new_schema = generate_new_schema(current_schema, tag_registry, new_version)
        
        # Write new schema version
        new_schema_path = SCHEMAS_DIR / f"community_submission.v{new_version}.schema.json"
        with open(new_schema_path, 'w') as f:
            json.dump(new_schema, f, indent=2)
        
        print(f"Created {new_schema_path}")
    else:
        print("No new tags found, schema is up to date")


if __name__ == "__main__":
    main()
