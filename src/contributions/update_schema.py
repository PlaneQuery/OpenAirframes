#!/usr/bin/env python3
"""
Update the schema with tag type definitions from existing submissions.

This script reads all community submissions and generates a new schema version
that includes explicit type definitions for all known tags.

When new tags are introduced, a new schema version is created (e.g., v1 -> v2 -> v3).

Usage:
    python -m src.contributions.update_schema
    python -m src.contributions.update_schema --check  # Check if update needed
"""
import argparse
import json
import sys
from pathlib import Path

from .read_community_data import read_all_submissions, build_tag_type_registry
from .schema import SCHEMAS_DIR, get_latest_schema_version, get_schema_path, load_schema


def get_existing_tag_definitions(schema: dict) -> dict[str, dict]:
    """Extract existing tag property definitions from schema."""
    tags_props = schema.get("properties", {}).get("tags", {}).get("properties", {})
    return tags_props


def type_name_to_json_schema(type_name: str) -> dict:
    """Convert a type name to a JSON Schema type definition."""
    type_map = {
        "string": {"type": "string"},
        "integer": {"type": "integer"},
        "number": {"type": "number"},
        "boolean": {"type": "boolean"},
        "null": {"type": "null"},
        "array": {"type": "array", "items": {"$ref": "#/$defs/tagScalar"}},
        "object": {"type": "object", "additionalProperties": {"$ref": "#/$defs/tagScalar"}},
    }
    return type_map.get(type_name, {"$ref": "#/$defs/tagValue"})


def generate_new_schema(base_schema: dict, tag_registry: dict[str, str], new_version: int) -> dict:
    """
    Generate a new schema version with explicit tag definitions.
    
    Args:
        base_schema: The current schema to base the new one on
        tag_registry: Dict mapping tag name to type name
        new_version: The new version number
        
    Returns:
        Complete new schema dict
    """
    schema = json.loads(json.dumps(base_schema))  # Deep copy
    
    # Update title with new version
    schema["title"] = f"PlaneQuery Aircraft Community Submission (v{new_version})"
    
    # Build tag properties with explicit types
    tag_properties = {}
    for tag_name, type_name in sorted(tag_registry.items()):
        tag_properties[tag_name] = type_name_to_json_schema(type_name)
    
    # Update tags definition
    schema["properties"]["tags"] = {
        "type": "object",
        "description": "Community-defined tags. New tags can be added, but must use consistent types.",
        "propertyNames": {
            "type": "string",
            "pattern": "^[a-z][a-z0-9_]{0,63}$"
        },
        "properties": tag_properties,
        # Still allow additional properties for new tags
        "additionalProperties": {"$ref": "#/$defs/tagValue"}
    }
    
    return schema


def check_for_new_tags(tag_registry: dict[str, str], current_schema: dict) -> list[str]:
    """
    Check which tags in the registry are not yet defined in the schema.
    
    Returns:
        List of new tag names
    """
    existing_tags = get_existing_tag_definitions(current_schema)
    return [tag for tag in tag_registry if tag not in existing_tags]


def create_new_schema_version(
    tag_registry: dict[str, str],
    check_only: bool = False
) -> tuple[int | None, list[str]]:
    """
    Create a new schema version if there are new tags.
    
    Args:
        tag_registry: Dict mapping tag name to type name
        check_only: If True, only check if update is needed without writing
        
    Returns:
        Tuple of (new_version or None if no update, list_of_new_tags)
    """
    current_version = get_latest_schema_version()
    current_schema = load_schema(current_version)
    
    # Find new tags
    new_tags = check_for_new_tags(tag_registry, current_schema)
    
    if not new_tags:
        return None, []
    
    if check_only:
        return current_version + 1, new_tags
    
    # Generate and write new schema
    new_version = current_version + 1
    new_schema = generate_new_schema(current_schema, tag_registry, new_version)
    new_schema_path = get_schema_path(new_version)
    
    with open(new_schema_path, "w") as f:
        json.dump(new_schema, f, indent=2)
        f.write("\n")
    
    return new_version, new_tags


def update_schema_from_submissions(check_only: bool = False) -> tuple[int | None, list[str]]:
    """
    Read all submissions and create a new schema version if needed.
    
    Args:
        check_only: If True, only check if update is needed without writing
        
    Returns:
        Tuple of (new_version or None if no update, list_of_new_tags)
    """
    submissions = read_all_submissions()
    tag_registry = build_tag_type_registry(submissions)
    return create_new_schema_version(tag_registry, check_only)


def main():
    parser = argparse.ArgumentParser(description="Update schema with tag definitions")
    parser.add_argument("--check", action="store_true", help="Check if update needed without writing")
    
    args = parser.parse_args()
    
    new_version, new_tags = update_schema_from_submissions(check_only=args.check)
    
    if args.check:
        if new_version:
            print(f"Schema update needed -> v{new_version}. New tags: {', '.join(new_tags)}")
            sys.exit(1)
        else:
            print(f"Schema is up to date (v{get_latest_schema_version()})")
            sys.exit(0)
    else:
        if new_version:
            print(f"Created {get_schema_path(new_version)}")
            print(f"Added tags: {', '.join(new_tags)}")
        else:
            print(f"No update needed (v{get_latest_schema_version()})")


if __name__ == "__main__":
    main()
