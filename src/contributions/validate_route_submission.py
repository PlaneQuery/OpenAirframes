#!/usr/bin/env python3
"""Validate a community route submission from a GitHub issue."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

from .routes import extract_routes_from_issue_body, parse_routes_text


VALIDATED_ROUTE_LABEL = "validated-routes"


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
        response_body = response.read()
        return json.loads(response_body) if response_body else {}


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
        pass


def validate_and_report(route_text: str, issue_number: int | None = None) -> bool:
    """Validate route text and optionally report back to the GitHub issue."""
    routes, errors = parse_routes_text(route_text)

    if errors:
        error_list = "\n".join(f"- {error}" for error in errors[:50])
        if len(errors) > 50:
            error_list += f"\n- ...and {len(errors) - 50} more error(s)"
        message = (
            "❌ **Route Validation Failed**\n\n"
            f"{error_list}\n\n"
            "Each non-empty line should look like `CALLSIGN ORIGIN DESTINATION`, "
            "with optional intermediate route codes."
        )

        print(message, file=sys.stderr)

        if issue_number:
            add_issue_comment(issue_number, message)
            remove_issue_label(issue_number, VALIDATED_ROUTE_LABEL)

        return False

    message = (
        "✅ **Route Validation Passed**\n\n"
        f"{len(routes)} route(s) validated successfully.\n\n"
        "A maintainer can approve this submission by adding the `approved` label."
    )

    print(message)

    if issue_number:
        add_issue_comment(issue_number, message)
        add_issue_label(issue_number, VALIDATED_ROUTE_LABEL)

    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate community route submission text")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--issue-body", help="Issue body text containing route data")
    source_group.add_argument("--issue-body-file", help="File containing issue body text")
    source_group.add_argument("--file", help="Route text file to validate")
    source_group.add_argument("--stdin", action="store_true", help="Read route text from stdin")
    parser.add_argument("--issue-number", type=int, help="GitHub issue number to comment on")

    args = parser.parse_args()

    if args.issue_body:
        route_text = extract_routes_from_issue_body(args.issue_body)
    elif args.issue_body_file:
        with open(args.issue_body_file) as f:
            route_text = extract_routes_from_issue_body(f.read())
    elif args.file:
        with open(args.file) as f:
            route_text = f.read()
    else:
        route_text = sys.stdin.read()

    if not route_text:
        message = (
            "❌ **Route Validation Failed**\n\n"
            "Could not extract route data. Paste routes in the `Route Data` field "
            "or attach a `.txt` file."
        )
        print(message, file=sys.stderr)
        if args.issue_number:
            add_issue_comment(args.issue_number, message)
        sys.exit(1)

    success = validate_and_report(route_text, args.issue_number)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
