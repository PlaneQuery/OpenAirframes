"""Utilities for community route submissions."""
from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


COMMUNITY_ROUTES_DIR = Path(__file__).parent.parent.parent / "community-routes"

CALLSIGN_RE = re.compile(r"^[A-Z0-9]{2,12}$")
ROUTE_CODE_RE = re.compile(r"^[A-Z0-9]{3,5}$")
ROUTE_SECTION_HEADERS = (
    "Route Data",
    "Routes",
    "Route Submission",
    "Submission Routes",
)


@dataclass(frozen=True)
class RouteEntry:
    callsign: str
    route: tuple[str, ...]
    line_number: int

    @property
    def normalized_line(self) -> str:
        return " ".join((self.callsign, *self.route))


def _strip_inline_comment(line: str) -> str:
    """Strip comment lines and inline comments."""
    if line.lstrip().startswith("#"):
        return ""
    return line.split("#", 1)[0].strip()


def parse_routes_text(text: str) -> tuple[list[RouteEntry], list[str]]:
    """
    Parse whitespace-delimited route text.

    Expected format per non-empty line:
        CALLSIGN ORIGIN [WAYPOINT ...] DESTINATION
    """
    routes: list[RouteEntry] = []
    errors: list[str] = []

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = _strip_inline_comment(raw_line)
        if not line:
            continue

        parts = [part.upper() for part in line.split()]
        if len(parts) < 3:
            errors.append(
                f"line {line_number}: expected CALLSIGN plus at least two route codes"
            )
            continue

        callsign = parts[0]
        route = tuple(parts[1:])

        if not CALLSIGN_RE.fullmatch(callsign):
            errors.append(
                f"line {line_number}: invalid callsign '{parts[0]}' "
                "(use 2-12 letters/numbers)"
            )

        invalid_codes = [code for code in route if not ROUTE_CODE_RE.fullmatch(code)]
        if invalid_codes:
            errors.append(
                f"line {line_number}: invalid route code(s) {', '.join(invalid_codes)} "
                "(use 3-5 letters/numbers)"
            )

        if not errors or not any(error.startswith(f"line {line_number}:") for error in errors):
            routes.append(RouteEntry(callsign=callsign, route=route, line_number=line_number))

    if not routes and not errors:
        errors.append("no route lines found")

    return routes, errors


def normalize_routes_text(text: str) -> str:
    """Return normalized route text with uppercase tokens and single spaces."""
    routes, errors = parse_routes_text(text)
    if errors:
        raise ValueError("\n".join(errors))
    return "\n".join(route.normalized_line for route in routes) + "\n"


def metadata_header(
    *,
    issue_number: int,
    contributor_uuid: str,
    creation_timestamp: str,
    contributor_name: str | None = None,
) -> str:
    """Build comment metadata for a persisted route submission file."""
    lines = [
        "# OpenAirframes community route submission",
        f"# source_issue: #{issue_number}",
        f"# contributor_uuid: {contributor_uuid}",
        f"# creation_timestamp: {creation_timestamp}",
    ]
    if contributor_name:
        lines.append(f"# contributor_name: {contributor_name}")
    lines.append("#")
    return "\n".join(lines) + "\n"


def parse_metadata_header(text: str) -> dict[str, str]:
    """Extract key/value metadata from leading comment lines."""
    metadata: dict[str, str] = {}
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if not stripped.startswith("#"):
            break
        comment = stripped[1:].strip()
        if ":" not in comment:
            continue
        key, value = comment.split(":", 1)
        metadata[key.strip()] = value.strip()
    return metadata


def download_github_attachment(url: str) -> str | None:
    """Download text content from a GitHub issue attachment URL."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "OpenAirframes-Bot"})
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read().decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError, UnicodeDecodeError) as e:
        print(f"Failed to download route attachment from {url}: {e}")
        return None


def _extract_section(body: str) -> str | None:
    for header in ROUTE_SECTION_HEADERS:
        pattern = rf"### {re.escape(header)}\s*\n([\s\S]*?)(?=\n###|\s*$)"
        match = re.search(pattern, body, flags=re.IGNORECASE)
        if match:
            section = match.group(1).strip()
            if section and section != "_No response_":
                return section
    return None


def _extract_attachment_url(text: str) -> str | None:
    patterns = [
        r"\[[^\]]+\]\((https://github\.com/[^\)]+)\)",
        r"(https://github\.com/(?:user-attachments/files|[^\s\)]+/files)/[^\s\)]+)",
        r"(https://github\.com/user-attachments/assets/[^\s\)]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def extract_routes_from_issue_body(body: str) -> str | None:
    """
    Extract route text from a GitHub issue body.

    Supports a route data section containing an attachment, fenced code block,
    or raw whitespace-delimited route lines.
    """
    section = _extract_section(body)
    search_text = section or body

    attachment_url = _extract_attachment_url(search_text)
    if attachment_url:
        content = download_github_attachment(attachment_url)
        if content:
            return content.strip()

    codeblock = re.search(r"```(?:text|txt|routes?)?\s*\n([\s\S]*?)\n\s*```", search_text)
    if codeblock:
        return codeblock.group(1).strip()

    if section:
        return section.strip()

    # Fallback for older issues: use parseable-looking route lines from the body.
    candidate_lines = []
    for raw_line in body.splitlines():
        line = _strip_inline_comment(raw_line)
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 3 and CALLSIGN_RE.fullmatch(parts[0].upper()):
            candidate_lines.append(line)

    if candidate_lines:
        return "\n".join(candidate_lines)

    return None
