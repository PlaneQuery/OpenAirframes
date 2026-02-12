#!/usr/bin/env python3
"""
Validate a community submission from a GitHub issue.

This script is called by the GitHub Actions workflow to validate
submissions when issues are opened or edited.

Usage:
    python -m src.contributions.validate_submission --issue-body "..."
    python -m src.contributions.validate_submission --issue-body-file /path/to/body.txt
    python -m src.contributions.validate_submission --file submission.json
    echo '{"registration_number": "N12345"}' | python -m src.contributions.validate_submission --stdin
    
Environment variables (for GitHub Actions):
    GITHUB_TOKEN: GitHub API token
    GITHUB_REPOSITORY: owner/repo
    ISSUE_NUMBER: Issue number to comment on
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.error

from .schema import extract_json_from_issue_body, parse_and_validate, load_schema
from .read_community_data import read_all_submissions, build_tag_type_registry, get_python_type_name


def github_api_request(method: str, endpoint: str, data: dict | None = None) -> dict:
    """Make a GitHub API request."""
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    
    if not token or not repo:
        raise EnvironmentError("GITHUB_TOKEN and GITHUB_REPOSITORY must be set")
    
    url = f"https://api.github.com/repos/{repo}{endpoint}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }
    
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def add_issue_comment(issue_number: int, body: str) -> None:
    """Add a comment to a GitHub issue."""
    github_api_request("POST", f"/issues/{issue_number}/comments", {"body": body})


def add_issue_label(issue_number: int, label: str) -> None:
    """Add a label to a GitHub issue."""
    github_api_request("POST", f"/issues/{issue_number}/labels", {"labels": [label]})


def remove_issue_label(issue_number: int, label: str) -> None:
    """Remove a label from a GitHub issue."""
    try:
        github_api_request("DELETE", f"/issues/{issue_number}/labels/{label}")
    except urllib.error.HTTPError:
        pass  # Label might not exist


def validate_tag_consistency(data: dict | list, tag_registry: dict[str, str]) -> list[str]:
    """
    Check that tag types in new submissions match existing tag types.
    
    Args:
        data: Single submission dict or list of submissions
        tag_registry: Dict mapping tag name to expected type
        
    Returns:
        List of error messages. Empty list means validation passed.
    """
    errors = []
    submissions = data if isinstance(data, list) else [data]
    
    for i, submission in enumerate(submissions):
        prefix = f"[{i}] " if len(submissions) > 1 else ""
        tags = submission.get("tags", {})
        
        if not isinstance(tags, dict):
            continue
        
        for key, value in tags.items():
            actual_type = get_python_type_name(value)
            
            if key in tag_registry:
                expected_type = tag_registry[key]
                if actual_type != expected_type:
                    errors.append(
                        f"{prefix}tags.{key}: expected type '{expected_type}', got '{actual_type}'"
                    )
    
    return errors


def validate_and_report(json_str: str, issue_number: int | None = None) -> bool:
    """
    Validate JSON and optionally report to GitHub issue.
    
    Args:
        json_str: JSON string to validate
        issue_number: Optional issue number to comment on
        
    Returns:
        True if validation passed, False otherwise
    """
    data, errors = parse_and_validate(json_str)
    
    if errors:
        error_list = "\n".join(f"- {e}" for e in errors)
        message = f"❌ **Validation Failed**\n\n{error_list}\n\nPlease fix the errors and edit your submission."
        
        print(message, file=sys.stderr)
        
        if issue_number:
            add_issue_comment(issue_number, message)
            remove_issue_label(issue_number, "validated")
        
        return False
    
    # Check tag type consistency against existing submissions
    if data is not None:
        try:
            existing_submissions = read_all_submissions()
            tag_registry = build_tag_type_registry(existing_submissions)
            tag_errors = validate_tag_consistency(data, tag_registry)
            
            if tag_errors:
                error_list = "\n".join(f"- {e}" for e in tag_errors)
                message = (
                    f"❌ **Tag Type Mismatch**\n\n"
                    f"Your submission uses tags with types that don't match existing submissions:\n\n"
                    f"{error_list}\n\n"
                    f"Please use the same type as existing tags, or use a different tag name."
                )
                
                print(message, file=sys.stderr)
                
                if issue_number:
                    add_issue_comment(issue_number, message)
                    remove_issue_label(issue_number, "validated")
                
                return False
        except Exception as e:
            # Don't fail validation if we can't read existing submissions
            print(f"Warning: Could not check tag consistency: {e}", file=sys.stderr)
    
    count = len(data) if isinstance(data, list) else 1
    message = f"✅ **Validation Passed**\n\n{count} submission(s) validated successfully against the schema.\n\nA maintainer can approve this submission by adding the `approved` label."
    
    print(message)
    
    if issue_number:
        add_issue_comment(issue_number, message)
        add_issue_label(issue_number, "validated")
    
    return True


def main():
    parser = argparse.ArgumentParser(description="Validate community submission JSON")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--issue-body", help="Issue body text containing JSON")
    source_group.add_argument("--issue-body-file", help="File containing issue body text")
    source_group.add_argument("--file", help="JSON file to validate")
    source_group.add_argument("--stdin", action="store_true", help="Read JSON from stdin")
    
    parser.add_argument("--issue-number", type=int, help="GitHub issue number to comment on")
    
    args = parser.parse_args()
    
    # Get JSON string
    if args.issue_body:
        json_str = extract_json_from_issue_body(args.issue_body)
        if not json_str:
            print("❌ Could not extract JSON from issue body", file=sys.stderr)
            if args.issue_number:
                add_issue_comment(
                    args.issue_number,
                    "❌ **Validation Failed**\n\nCould not extract JSON from submission. "
                    "Please ensure your JSON is in the 'Submission JSON' field wrapped in code blocks."
                )
            sys.exit(1)
    elif args.issue_body_file:
        with open(args.issue_body_file) as f:
            issue_body = f.read()
        json_str = extract_json_from_issue_body(issue_body)
        if not json_str:
            print("❌ Could not extract JSON from issue body", file=sys.stderr)
            print(f"Issue body:\n{issue_body}", file=sys.stderr)
            if args.issue_number:
                add_issue_comment(
                    args.issue_number,
                    "❌ **Validation Failed**\n\nCould not extract JSON from submission. "
                    "Please ensure your JSON is in the 'Submission JSON' field."
                )
            sys.exit(1)
    elif args.file:
        with open(args.file) as f:
            json_str = f.read()
    else:  # stdin
        json_str = sys.stdin.read()
    
    # Validate
    success = validate_and_report(json_str, args.issue_number)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
