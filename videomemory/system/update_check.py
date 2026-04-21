"""Update-check helpers for the VideoMemory web UI."""

from __future__ import annotations

import json
import re
import subprocess
import time
from itertools import zip_longest
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

DEFAULT_UPDATE_MANIFEST_URL = (
    "https://raw.githubusercontent.com/Clamepending/videomemory/main/docs/update-manifest.json"
)


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def read_project_version(repo_root: Path) -> str:
    """Read the package version from pyproject.toml without adding a TOML dependency."""
    pyproject_path = repo_root / "pyproject.toml"
    try:
        text = pyproject_path.read_text(encoding="utf-8")
    except OSError:
        return ""

    match = re.search(r"(?m)^version\s*=\s*[\"']([^\"']+)[\"']", text)
    return match.group(1).strip() if match else ""


def _version_parts(version: str) -> list[int]:
    cleaned = _clean_text(version).lstrip("vV")
    match = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?", cleaned)
    if not match:
        return []
    return [int(part or 0) for part in match.groups()]


def compare_versions(current_version: str, latest_version: str) -> int:
    """Compare two mostly-semver version strings.

    Returns -1 when current < latest, 0 when equal, and 1 when current > latest.
    Pre-release labels are intentionally ignored; VideoMemory release tags are
    expected to use simple vX.Y.Z versions.
    """
    current_parts = _version_parts(current_version)
    latest_parts = _version_parts(latest_version)
    for current_part, latest_part in zip_longest(current_parts, latest_parts, fillvalue=0):
        if current_part < latest_part:
            return -1
        if current_part > latest_part:
            return 1
    return 0


def _run_git(repo_root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def get_git_revision_info(repo_root: Path) -> Dict[str, str]:
    """Return best-effort git branch/tag/commit details for the running checkout."""
    commit = _run_git(repo_root, "rev-parse", "--short=12", "HEAD")
    branch = _run_git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":
        branch = ""
    tag = _run_git(repo_root, "describe", "--tags", "--exact-match", "HEAD")
    return {
        "current_commit": commit,
        "current_branch": branch,
        "current_tag": tag,
    }


def fetch_update_manifest(manifest_url: str, timeout_s: float = 2.0) -> Dict[str, Any]:
    """Fetch a JSON update manifest from HTTP(S), file://, or a local path."""
    manifest_url = _clean_text(manifest_url)
    if not manifest_url:
        raise ValueError("update manifest URL is empty")

    parsed = urlparse(manifest_url)
    if parsed.scheme in ("http", "https"):
        request = Request(
            manifest_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "VideoMemory update checker",
            },
        )
        try:
            with urlopen(request, timeout=timeout_s) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            raise RuntimeError(f"update manifest returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"update manifest request failed: {exc.reason}") from exc
    elif parsed.scheme == "file":
        raw = Path(unquote(parsed.path)).read_text(encoding="utf-8")
    elif parsed.scheme == "":
        raw = Path(manifest_url).read_text(encoding="utf-8")
    else:
        raise ValueError(f"unsupported update manifest scheme: {parsed.scheme}")

    parsed_manifest = json.loads(raw)
    if not isinstance(parsed_manifest, dict):
        raise ValueError("update manifest must be a JSON object")
    return parsed_manifest


def build_update_payload(
    repo_root: Path,
    manifest_url: Optional[str] = None,
    fetch_timeout_s: float = 2.0,
) -> Dict[str, Any]:
    """Build the payload returned by /api/version.

    The function never raises for network/manifest failures; callers still get
    the current app version and git revision so the UI can fail quietly offline.
    """
    resolved_manifest_url = (
        DEFAULT_UPDATE_MANIFEST_URL if manifest_url is None else _clean_text(manifest_url)
    )
    current_version = read_project_version(repo_root)
    git_info = get_git_revision_info(repo_root)
    payload: Dict[str, Any] = {
        "status": "success",
        "app": "videomemory",
        "current_version": current_version,
        "manifest_url": resolved_manifest_url,
        "latest_version": "",
        "latest_git_ref": "",
        "latest_commit": "",
        "release_notes_url": "",
        "update_command": "",
        "update_available": None,
        "check_error": "",
        "checked_at": int(time.time()),
        **git_info,
    }

    if not resolved_manifest_url:
        payload["check_error"] = "update check disabled"
        return payload

    try:
        manifest = fetch_update_manifest(resolved_manifest_url, timeout_s=fetch_timeout_s)
    except Exception as exc:
        payload["check_error"] = str(exc)
        return payload

    latest_version = _clean_text(manifest.get("latest_version"))
    payload.update(
        {
            "schema_version": manifest.get("schema_version", 1),
            "channel": _clean_text(manifest.get("channel")) or "stable",
            "latest_version": latest_version,
            "latest_git_ref": _clean_text(manifest.get("latest_git_ref")),
            "latest_commit": _clean_text(manifest.get("latest_commit")),
            "release_notes_url": _clean_text(manifest.get("release_notes_url")),
            "update_command": _clean_text(manifest.get("update_command")),
            "published_at": _clean_text(manifest.get("published_at")),
            "message": _clean_text(manifest.get("message")),
        }
    )

    if current_version and latest_version:
        payload["update_available"] = compare_versions(current_version, latest_version) < 0

    return payload
