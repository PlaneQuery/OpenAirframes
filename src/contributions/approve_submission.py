#!/usr/bin/env python3
"""
Approve a community submission and create a PR.

This script is called by the GitHub Actions workflow when the 'approved'
label is added to a validated submission issue.

Usage:
    python -m src.contributions.approve_submission --issue-number 123 --issue-body "..." --author "username" --author-id 12345

Environment variables:
    GITHUB_TOKEN: GitHub API token with repo write permissions
    GITHUB_REPOSITORY: owner/repo
"""
import argparse
import base64
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

from .schema import extract_json_from_issue_body, extract_contributor_name_from_issue_body, parse_and_validate, load_schema, SCHEMAS_DIR
from .contributor import (
    generate_contributor_uuid,
    generate_submission_filename,
    compute_content_hash,
)
from .update_schema import generate_updated_schema, check_for_new_tags, get_existing_tag_definitions
from .read_community_data import build_tag_type_registry


def github_api_request(
    method: str, 
    endpoint: str, 
    data: dict | None = None,
    accept: str = "application/vnd.github.v3+json"
) -> dict:
    """Make a GitHub API request."""
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    
    if not token or not repo:
        raise EnvironmentError("GITHUB_TOKEN and GITHUB_REPOSITORY must be set")
    
    url = f"https://api.github.com/repos/{repo}{endpoint}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": accept,
        "Content-Type": "application/json",
    }
    
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req) as response:
            response_body = response.read()
            # DELETE requests return empty body (204 No Content)
            if not response_body:
                return {}
            return json.loads(response_body)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        print(f"GitHub API error: {e.code} {e.reason}: {error_body}", file=sys.stderr)
        raise


def add_issue_comment(issue_number: int, body: str) -> None:
    """Add a comment to a GitHub issue."""
    github_api_request("POST", f"/issues/{issue_number}/comments", {"body": body})


def get_default_branch_sha() -> str:
    """Get the SHA of the default branch (main)."""
    ref = github_api_request("GET", "/git/ref/heads/main")
    return ref["object"]["sha"]


def create_branch(branch_name: str, sha: str) -> None:
    """Create a new branch from a SHA."""
    try:
        github_api_request("POST", "/git/refs", {
            "ref": f"refs/heads/{branch_name}",
            "sha": sha,
        })
    except urllib.error.HTTPError as e:
        if e.code == 422:  # Branch exists
            # Delete and recreate
            try:
                github_api_request("DELETE", f"/git/refs/heads/{branch_name}")
            except urllib.error.HTTPError:
                pass
            github_api_request("POST", "/git/refs", {
                "ref": f"refs/heads/{branch_name}",
                "sha": sha,
            })
        else:
            raise


def get_file_sha(path: str, branch: str) -> str | None:
    """Get the SHA of an existing file, or None if it doesn't exist."""
    try:
        response = github_api_request("GET", f"/contents/{path}?ref={branch}")
        return response.get("sha")
    except Exception:
        return None


def create_or_update_file(path: str, content: str, message: str, branch: str) -> None:
    """Create or update a file in the repository."""
    content_b64 = base64.b64encode(content.encode()).decode()
    payload = {
        "message": message,
        "content": content_b64,
        "branch": branch,
    }
    
    # If file exists, we need to include its SHA to update it
    sha = get_file_sha(path, branch)
    if sha:
        payload["sha"] = sha
    
    github_api_request("PUT", f"/contents/{path}", payload)


def create_pull_request(title: str, head: str, base: str, body: str) -> dict:
    """Create a pull request."""
    return github_api_request("POST", "/pulls", {
        "title": title,
        "head": head,
        "base": base,
        "body": body,
    })


def add_labels_to_issue(issue_number: int, labels: list[str]) -> None:
    """Add labels to an issue or PR."""
    github_api_request("POST", f"/issues/{issue_number}/labels", {"labels": labels})


def process_submission(
    issue_number: int,
    issue_body: str,
    author_username: str,
    author_id: int,
) -> bool:
    """
    Process an approved submission and create a PR.
    
    Args:
        issue_number: The GitHub issue number
        issue_body: The issue body text
        author_username: The GitHub username of the issue author
        author_id: The numeric GitHub user ID
        
    Returns:
        True if successful, False otherwise
    """
    # Extract and validate JSON
    json_str = extract_json_from_issue_body(issue_body)
    if not json_str:
        add_issue_comment(issue_number, "❌ Could not extract JSON from submission.")
        return False
    
    data, errors = parse_and_validate(json_str)
    if errors or data is None:
        error_list = "\n".join(f"- {e}" for e in errors) if errors else "Unknown error"
        add_issue_comment(issue_number, f"❌ **Validation Failed**\n\n{error_list}")
        return False
    
    # Normalize to list
    submissions: list[dict] = data if isinstance(data, list) else [data]
    
    # Generate contributor UUID from GitHub ID
    contributor_uuid = generate_contributor_uuid(author_id)
    
    # Extract contributor name from issue form (None means user opted out of attribution)
    contributor_name = extract_contributor_name_from_issue_body(issue_body)
    
    # Add metadata to each submission
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    timestamp_str = now.isoformat()
    
    for submission in submissions:
        submission["contributor_uuid"] = contributor_uuid
        if contributor_name:
            submission["contributor_name"] = contributor_name
        submission["creation_timestamp"] = timestamp_str
    
    # Generate unique filename
    content_json = json.dumps(submissions, indent=2, sort_keys=True)
    content_hash = compute_content_hash(content_json)
    filename = generate_submission_filename(author_username, date_str, content_hash)
    file_path = f"community/{date_str}/{filename}"
    
    # Create branch
    branch_name = f"community-submission-{issue_number}"
    default_sha = get_default_branch_sha()
    create_branch(branch_name, default_sha)
    
    # Create file
    commit_message = f"Add community submission from @{author_username} (closes #{issue_number})"
    create_or_update_file(file_path, content_json, commit_message, branch_name)
    
    # Update schema with any new tags (modifies v1 in place)
    schema_updated = False
    new_tags = []
    try:
        # Build tag registry from new submissions
        tag_registry = build_tag_type_registry(submissions)
        
        # Get current schema and merge existing tags
        current_schema = load_schema()
        existing_tags = get_existing_tag_definitions(current_schema)
        
        # Merge existing tags into registry
        for tag_name, tag_def in existing_tags.items():
            if tag_name not in tag_registry:
                tag_type = tag_def.get("type", "string")
                tag_registry[tag_name] = tag_type
        
        # Check for new tags
        new_tags = check_for_new_tags(tag_registry, current_schema)
        
        if new_tags:
            # Generate updated schema
            updated_schema = generate_updated_schema(current_schema, tag_registry)
            schema_json = json.dumps(updated_schema, indent=2) + "\n"
            
            create_or_update_file(
                "schemas/community_submission.v1.schema.json",
                schema_json,
                f"Update schema with new tags: {', '.join(new_tags)}",
                branch_name
            )
            schema_updated = True
    except Exception as e:
        print(f"Warning: Could not update schema: {e}", file=sys.stderr)
    
    # Create PR
    schema_note = ""
    if schema_updated:
        schema_note = f"\n**Schema Updated:** Added new tags: `{', '.join(new_tags)}`\n"
    
    pr_body = f"""## Community Submission

Adds {len(submissions)} submission(s) from @{author_username}.

**File:** `{file_path}`
**Contributor UUID:** `{contributor_uuid}`
{schema_note}
Closes #{issue_number}

---

### Submissions
```json
{content_json}
```"""
    
    pr = create_pull_request(
        title=f"Community submission: {filename}",
        head=branch_name,
        base="main",
        body=pr_body,
    )
    
    # Add labels to PR
    add_labels_to_issue(pr["number"], ["community", "auto-generated"])
    
    # Comment on original issue
    add_issue_comment(
        issue_number,
        f"✅ **Submission Approved**\n\n"
        f"PR #{pr['number']} has been created to add your submission.\n\n"
        f"**File:** `{file_path}`\n"
        f"**Your Contributor UUID:** `{contributor_uuid}`\n\n"
        f"The PR will be merged by a maintainer."
    )
    
    print(f"Created PR #{pr['number']} for submission")
    return True


def main():
    parser = argparse.ArgumentParser(description="Approve community submission and create PR")
    parser.add_argument("--issue-number", type=int, required=True, help="GitHub issue number")
    parser.add_argument("--issue-body", required=True, help="Issue body text")
    parser.add_argument("--author", required=True, help="Issue author username")
    parser.add_argument("--author-id", type=int, required=True, help="Issue author numeric ID")
    
    args = parser.parse_args()
    
    success = process_submission(
        issue_number=args.issue_number,
        issue_body=args.issue_body,
        author_username=args.author,
        author_id=args.author_id,
    )
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
