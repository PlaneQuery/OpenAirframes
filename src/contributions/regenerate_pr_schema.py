#!/usr/bin/env python3
"""
Regenerate schema for a PR branch after main has been merged in.
This script looks at the submission files in this branch and updates
the schema if new tags were introduced.

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
    generate_updated_schema,
)
from src.contributions.schema import load_schema, SCHEMAS_DIR


def main():
    """Main entry point."""
    # Load current schema
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
        print(f"Found new tags: {new_tags}")
        print("Updating schema...")
        
        # Generate updated schema
        updated_schema = generate_updated_schema(current_schema, tag_registry)
        
        # Write updated schema (in place)
        schema_path = SCHEMAS_DIR / "community_submission.v1.schema.json"
        with open(schema_path, 'w') as f:
            json.dump(updated_schema, f, indent=2)
            f.write("\n")
        
        print(f"Updated {schema_path}")
    else:
        print("No new tags found, schema is up to date")


if __name__ == "__main__":
    main()
