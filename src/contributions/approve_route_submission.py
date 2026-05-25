#!/usr/bin/env python3
"""Approve a community route submission and create a PR."""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

from .contributor import (
    compute_content_hash,
    generate_contributor_uuid,
    generate_submission_filename,
)
from .routes import (
    extract_routes_from_issue_body,
    metadata_header,
    normalize_routes_text,
    parse_routes_text,
)
from .schema import extract_contributor_name_from_issue_body


def github_api_request(
    method: str,
    endpoint: str,
    data: dict | None = None,
    accept: str = "application/vnd.github.v3+json",
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
            return json.loads(response_body) if response_body else {}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        print(f"GitHub API error: {e.code} {e.reason}: {error_body}", file=sys.stderr)
        raise


def add_issue_comment(issue_number: int, body: str) -> None:
    """Add a comment to a GitHub issue."""
    github_api_request("POST", f"/issues/{issue_number}/comments", {"body": body})


def get_default_branch_sha() -> str:
    """Get the SHA of the default branch."""
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
        if e.code == 422:
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
    """Get the SHA of an existing file, or None if it does not exist."""
    try:
        response = github_api_request("GET", f"/contents/{path}?ref={branch}")
        return response.get("sha")
    except Exception:
        return None


def create_or_update_file(path: str, content: str, message: str, branch: str) -> None:
    """Create or update a file in the repository."""
    payload: dict[str, str] = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
        "branch": branch,
    }

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
    """Process an approved route submission and create a PR."""
    route_text = extract_routes_from_issue_body(issue_body)
    if not route_text:
        add_issue_comment(issue_number, "❌ Could not extract route data from submission.")
        return False

    routes, errors = parse_routes_text(route_text)
    if errors:
        error_list = "\n".join(f"- {error}" for error in errors[:50])
        if len(errors) > 50:
            error_list += f"\n- ...and {len(errors) - 50} more error(s)"
        add_issue_comment(issue_number, f"❌ **Route Validation Failed**\n\n{error_list}")
        return False

    normalized_routes = normalize_routes_text(route_text)
    contributor_uuid = generate_contributor_uuid(author_id)
    contributor_name = extract_contributor_name_from_issue_body(issue_body)

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    timestamp_str = now.isoformat()

    content = (
        metadata_header(
            issue_number=issue_number,
            contributor_uuid=contributor_uuid,
            contributor_name=contributor_name,
            creation_timestamp=timestamp_str,
        )
        + normalized_routes
    )

    content_hash = compute_content_hash(normalized_routes)
    filename = generate_submission_filename(author_username, date_str, content_hash, ".txt")
    file_path = f"community-routes/{date_str}/{filename}"

    branch_name = f"community-route-submission-{issue_number}"
    default_sha = get_default_branch_sha()
    create_branch(branch_name, default_sha)

    commit_message = f"Add community route submission from @{author_username} (closes #{issue_number})"
    create_or_update_file(file_path, content, commit_message, branch_name)

    max_preview_lines = 50
    preview_lines = normalized_routes.splitlines()[:max_preview_lines]
    preview = "\n".join(preview_lines)
    preview_note = ""
    if len(routes) > max_preview_lines:
        preview_note = f"\n\n*Showing {max_preview_lines} of {len(routes)} routes.*"

    pr_body = f"""## Community Route Submission

Adds {len(routes)} route(s) from @{author_username}.

**File:** `{file_path}`
**Contributor UUID:** `{contributor_uuid}`

Closes #{issue_number}

---

### Routes
```text
{preview}
```{preview_note}"""

    pr = create_pull_request(
        title=f"Community route submission: {filename}",
        head=branch_name,
        base="main",
        body=pr_body,
    )

    add_labels_to_issue(pr["number"], ["community-routes", "auto-generated"])

    add_issue_comment(
        issue_number,
        f"✅ **Route Submission Approved**\n\n"
        f"PR #{pr['number']} has been created to add your route submission.\n\n"
        f"**File:** `{file_path}`\n"
        f"**Your Contributor UUID:** `{contributor_uuid}`\n\n"
        f"The PR will be merged by a maintainer."
    )

    print(f"Created PR #{pr['number']} for route submission")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Approve community route submission and create PR")
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
