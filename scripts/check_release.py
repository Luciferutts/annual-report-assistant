#!/usr/bin/env python3
"""Check publication candidates without printing secret values.

This is a bounded source hygiene check, not a complete secret or security audit.
In a Git repository it checks tracked files and non-ignored untracked files. Run
it after staging changes to check the exact candidate set. --strict-tree also
rejects local runtime directories in a distribution folder.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIRS = {
    ".venv", "venv", "node_modules", ".openharness", ".openharness-venv",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache",
    "build", "dist", ".claude", ".agents",
}
UNSAFE_LEGACY_TESTS = {
    "test_real_large_tasks.py", "test_hooks_skills_plugins_real.py",
    "test_untested_features.py", "test_merged_prs_on_autoagent.py",
}
SENSITIVE_NAMES = {
    "credentials.json", "auth.json", "copilot_auth.json", "settings.local.json",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".DS_Store", "Thumbs.db",
}
BINARY_SUFFIXES = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff",
    ".woff2", ".ttf", ".eot", ".otf", ".mp3", ".mp4", ".zip", ".gz",
    ".whl", ".so", ".dylib", ".dll", ".exe", ".pyc", ".pyo",
}
GENERIC_USERS = {
    "user", "username", "test", "testuser", "test-user", "test_user", "alice",
    "bob", "example", "yourname", "your-user", "your_user", "your_username",
    "runner", "me", "u", "dev", "developer", "someone", "用户名", "用户", "xxx",
}
PATTERNS = {
    "api_key_literal": re.compile(r"\b(?:sk|sk-ant|sk-proj)-[A-Za-z0-9_-]{20,}\b"),
    "github_token_literal": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    "aws_access_key_literal": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "google_api_key_literal": re.compile(r"\bAIza[A-Za-z0-9_-]{35}\b"),
    "groq_api_key_literal": re.compile(r"\bgsk_[A-Za-z0-9]{30,}\b"),
    "huggingface_token_literal": re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"),
    "slack_token_literal": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "jwt_literal": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b"),
    "private_key_literal": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
}
HOME_PATH = re.compile(r"/(?:Users|home)/([^/\s<>\"'`]+)")


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    category: str


def _git_candidates() -> list[Path] | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--show-toplevel"],
            check=False, capture_output=True, text=True,
        )
        if result.returncode or Path(result.stdout.strip()).resolve() != ROOT:
            return None
        result = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            check=False, capture_output=True,
        )
        if result.returncode:
            return None
        return sorted({ROOT / value.decode("utf-8", errors="surrogateescape")
                       for value in result.stdout.split(b"\0") if value})
    except (OSError, ValueError):
        return None


def _placeholder(value: str) -> bool:
    lowered = value.lower()
    return (
        lowered.startswith(("sk-test", "sk-dummy", "sk-example", "sk-fake", "sk-placeholder"))
        or "example" in lowered or "not-a-real" in lowered or "placeholder" in lowered
    )


def check(strict_tree: bool = False) -> dict:
    git_files = _git_candidates()
    scope = "git-publication-candidates" if git_files is not None else "source-tree"
    findings: set[Finding] = set()
    if git_files is None:
        files = []
        for path in ROOT.rglob("*"):
            rel = path.relative_to(ROOT)
            if ".git" in rel.parts or any(part in RUNTIME_DIRS for part in rel.parts):
                continue
            if path.is_file() or path.is_symlink():
                files.append(path)
    else:
        files = git_files

    if strict_tree:
        for path in ROOT.rglob("*"):
            rel = path.relative_to(ROOT)
            if ".git" in rel.parts:
                continue
            if path.name in RUNTIME_DIRS and path.is_dir():
                findings.add(Finding(str(rel), 0, "local_runtime_directory"))
            if path.is_file() and (
                path.name in SENSITIVE_NAMES or path.suffix.lower() in {".pem", ".p12", ".pfx", ".key"}
            ):
                findings.add(Finding(str(rel), 0, "sensitive_filename"))
            if path.is_file() and path.name.startswith(".env") and not path.name.endswith((".example", ".sample")):
                findings.add(Finding(str(rel), 0, "environment_file"))

    scanned = skipped = 0
    for path in files:
        rel = path.relative_to(ROOT)
        name = str(rel)
        if path.is_symlink():
            findings.add(Finding(name, 0, "symlink_requires_review"))
            continue
        if any(part in RUNTIME_DIRS for part in rel.parts):
            findings.add(Finding(name, 0, "tracked_runtime_file"))
            continue
        if path.name in UNSAFE_LEGACY_TESTS:
            findings.add(Finding(name, 0, "unsafe_legacy_real_service_test"))
        if path.name in SENSITIVE_NAMES or path.suffix.lower() in {".pem", ".p12", ".pfx", ".key"}:
            findings.add(Finding(name, 0, "sensitive_filename"))
        if path.name.startswith(".env") and not path.name.endswith((".example", ".sample")):
            findings.add(Finding(name, 0, "environment_file"))
        if rel.parts[:2] == (".github", "workflows") and path.name.startswith("autopilot-"):
            findings.add(Finding(name, 0, "legacy_autopilot_workflow"))
        if path.suffix.lower() in BINARY_SUFFIXES:
            skipped += 1
            continue
        try:
            raw = path.read_bytes()
            if b"\0" in raw[:8192]:
                skipped += 1
                continue
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            skipped += 1
            continue
        except OSError:
            findings.add(Finding(name, 0, "unreadable_publication_candidate"))
            continue
        scanned += 1
        for line_number, line in enumerate(content.splitlines(), 1):
            for category, pattern in PATTERNS.items():
                if any(not _placeholder(match.group()) for match in pattern.finditer(line)):
                    findings.add(Finding(name, line_number, category))
            for match in HOME_PATH.finditer(line):
                username = match.group(1)
                if username.lower() in GENERIC_USERS or any(char in username for char in "{}[]$*~"):
                    continue
                findings.add(Finding(name, line_number, "personal_absolute_home_path"))
    return {
        "scope": scope, "text_files_checked": scanned, "binary_files_not_inspected": skipped,
        "findings": [asdict(item) for item in sorted(findings)],
        "limitations": "Pattern-based publication hygiene only; does not inspect binary metadata or prove absence of all secrets.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict-tree", action="store_true", help="Also reject local runtime directories in a clean release folder")
    options = parser.parse_args()
    result = check(options.strict_tree)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
