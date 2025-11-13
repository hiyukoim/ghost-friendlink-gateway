#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = REPO_ROOT / "ghost_gateway" / "VERSION"


def format_version(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return "dev"
    match = re.match(r"v(\d+\.\d+)\.(\d+)-(\d+)-g[0-9a-f]+", raw)
    if match:
        base = match.group(1)
        patch = match.group(3)
        return f"{base}.{patch}"
    return raw


def detect_version() -> str:
    try:
        described = subprocess.check_output(
            ["git", "describe", "--tags", "--match", "v*.*.*", "--long"],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
        ).decode()
        return format_version(described)
    except Exception:
        try:
            commit = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=REPO_ROOT,
                stderr=subprocess.DEVNULL,
            ).decode().strip()
            return f"dev+{commit}"
        except Exception:
            return "dev"


def main() -> None:
    version = detect_version()
    VERSION_FILE.write_text(version + "\n")
    print(f"Embedded version: {version}")


if __name__ == "__main__":
    main()
