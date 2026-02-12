"""Schema validation for community submissions."""
import json
import re
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None


SCHEMAS_DIR = Path(__file__).parent.parent.parent / "schemas"

# For backwards compatibility
SCHEMA_PATH = SCHEMAS_DIR / "community_submission.v1.schema.json"


def get_latest_schema_version() -> int:
    """
    Find the latest schema version number.
    
    Returns:
        Latest version number (e.g., 1, 2, 3)
    """
    import re
    pattern = re.compile(r"community_submission\.v(\d+)\.schema\.json$")
    max_version = 0
    
    for path in SCHEMAS_DIR.glob("community_submission.v*.schema.json"):
        match = pattern.search(path.name)
        if match:
            version = int(match.group(1))
            max_version = max(max_version, version)
    
    return max_version


def get_schema_path(version: int | None = None) -> Path:
    """
    Get path to a specific schema version, or latest if version is None.
    
    Args:
        version: Schema version number, or None for latest
        
    Returns:
        Path to schema file
    """
    if version is None:
        version = get_latest_schema_version()
    return SCHEMAS_DIR / f"community_submission.v{version}.schema.json"


def load_schema(version: int | None = None) -> dict:
    """
    Load the community submission schema.
    
    Args:
        version: Schema version to load. If None, loads the latest version.
        
    Returns:
        Schema dict
    """
    schema_path = get_schema_path(version)
    with open(schema_path) as f:
        return json.load(f)


def validate_submission(data: dict | list, schema: dict | None = None) -> list[str]:
    """
    Validate submission(s) against schema.
    
    Args:
        data: Single submission dict or list of submissions
        schema: Optional schema dict. If None, loads from default path.
        
    Returns:
        List of error messages. Empty list means validation passed.
    """
    if Draft202012Validator is None:
        raise ImportError("jsonschema is required: pip install jsonschema")
    
    if schema is None:
        schema = load_schema()
    
    submissions = data if isinstance(data, list) else [data]
    errors = []
    
    validator = Draft202012Validator(schema)
    
    for i, submission in enumerate(submissions):
        prefix = f"[{i}] " if len(submissions) > 1 else ""
        for error in validator.iter_errors(submission):
            path = ".".join(str(p) for p in error.path) if error.path else "(root)"
            errors.append(f"{prefix}{path}: {error.message}")
    
    return errors


def download_github_attachment(url: str) -> str | None:
    """
    Download content from a GitHub attachment URL.
    
    Args:
        url: GitHub attachment URL (e.g., https://github.com/user-attachments/files/...)
        
    Returns:
        File content as string, or None if download failed
    """
    import urllib.request
    import urllib.error
    
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PlaneQuery-Bot"})
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read().decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError, UnicodeDecodeError) as e:
        print(f"Failed to download attachment from {url}: {e}")
        return None


def extract_json_from_issue_body(body: str) -> str | None:
    """
    Extract JSON from GitHub issue body.
    
    Looks for JSON in the 'Submission JSON' section, either:
    - A GitHub file attachment URL (drag-and-drop .json file)
    - Wrapped in code blocks (```json ... ``` or ``` ... ```)
    - Or raw JSON after the header
    
    Args:
        body: The issue body text
        
    Returns:
        Extracted JSON string or None if not found
    """
    # Try: GitHub attachment URL in the Submission JSON section
    # Format: [filename.json](https://github.com/user-attachments/files/...)
    # Or just the raw URL
    pattern_attachment = r"### Submission JSON\s*\n[\s\S]*?(https://github\.com/(?:user-attachments/files|.*?/files)/[^\s\)\]]+\.json)"
    match = re.search(pattern_attachment, body)
    if match:
        url = match.group(1)
        content = download_github_attachment(url)
        if content:
            return content.strip()
    
    # Also check for GitHub user-attachments URL anywhere in submission section
    pattern_attachment_alt = r"\[.*?\.json\]\((https://github\.com/[^\)]+)\)"
    match = re.search(pattern_attachment_alt, body)
    if match:
        url = match.group(1)
        if ".json" in url or "user-attachments" in url:
            content = download_github_attachment(url)
            if content:
                return content.strip()
    
    # Try: JSON in code blocks after "### Submission JSON"
    pattern_codeblock = r"### Submission JSON\s*\n\s*```(?:json)?\s*\n([\s\S]*?)\n\s*```"
    match = re.search(pattern_codeblock, body)
    if match:
        return match.group(1).strip()
    
    # Try: Raw JSON after "### Submission JSON" until next section or end
    pattern_raw = r"### Submission JSON\s*\n\s*([\[{][\s\S]*?[\]}])(?=\n###|\n\n###|$)"
    match = re.search(pattern_raw, body)
    if match:
        return match.group(1).strip()
    
    # Try: Any JSON object/array in the body (fallback)
    pattern_any = r"([\[{][\s\S]*?[\]}])"
    for match in re.finditer(pattern_any, body):
        candidate = match.group(1).strip()
        # Validate it looks like JSON
        if candidate.startswith('{') and candidate.endswith('}'):
            return candidate
        if candidate.startswith('[') and candidate.endswith(']'):
            return candidate
    
    return None


def extract_contributor_name_from_issue_body(body: str) -> str | None:
    """
    Extract contributor name from GitHub issue body.
    
    Looks for the 'Contributor Name' field in the issue form.
    
    Args:
        body: The issue body text
        
    Returns:
        Contributor name string or None if not found/empty
    """
    # Match "### Contributor Name" section
    pattern = r"### Contributor Name\s*\n\s*(.+?)(?=\n###|\n\n|$)"
    match = re.search(pattern, body)
    
    if match:
        name = match.group(1).strip()
        # GitHub issue forms show "_No response_" for empty optional fields
        if name and name != "_No response_":
            return name
    
    return None


def parse_and_validate(json_str: str, schema: dict | None = None) -> tuple[list | dict | None, list[str]]:
    """
    Parse JSON string and validate against schema.
    
    Args:
        json_str: JSON string to parse
        schema: Optional schema dict
        
    Returns:
        Tuple of (parsed data or None, list of errors)
    """
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        return None, [f"Invalid JSON: {e}"]
    
    errors = validate_submission(data, schema)
    return data, errors
