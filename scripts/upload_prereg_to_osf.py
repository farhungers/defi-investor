"""Upload pre-registration artifacts to OSF for cryptographic timestamping.

Each file is PUT to the OSF WaterButler API under the node configured by
`OSF_PROJECT_ID`. OSF records `date_modified` (and OSF-side hash) at ingest,
producing a timestamp that cannot be backdated. Combined with the git commit
hash embedded in each pre-registration's frontmatter, this establishes
priority of authorship for the hypothesis.

Runs today. Called manually or from CI on `prereg-*-v*` tag pushes.

Usage:
    python scripts/upload_prereg_to_osf.py FRAME_C1.md HYPOTHESIS_A2a.md A2a.yaml
    python scripts/upload_prereg_to_osf.py --all        # every file in docs/preregistrations/

Env:
    OSF_TOKEN         personal access token with osf.full_write
    OSF_PROJECT_ID    5-char node id (e.g. 98kez)
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

PREREG_DIR = Path("docs/preregistrations")
API_ROOT = "https://api.osf.io/v2"
WB_ROOT = "https://files.osf.io/v1"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def list_existing(node_id: str, token: str) -> dict[str, dict]:
    """Return {filename: node_dict} for files already at the root of osfstorage."""
    url = f"{API_ROOT}/nodes/{node_id}/files/osfstorage/"
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    out: dict[str, dict] = {}
    for item in r.json().get("data", []):
        attrs = item.get("attributes", {})
        if attrs.get("kind") == "file":
            out[attrs["name"]] = item
    return out


def upload_or_update(local: Path, node_id: str, token: str, existing: dict[str, dict]) -> tuple[str, str]:
    """Return (action, remote_hash). action in {'created', 'updated', 'unchanged'}."""
    filename = local.name
    local_sha = sha256(local)
    headers = {"Authorization": f"Bearer {token}"}

    if filename in existing:
        remote_sha = existing[filename]["attributes"]["extra"]["hashes"]["sha256"]
        if remote_sha == local_sha:
            return ("unchanged", remote_sha)
        upload_url = existing[filename]["links"]["upload"]
        with local.open("rb") as f:
            r = requests.put(upload_url, headers=headers, data=f, timeout=60)
        r.raise_for_status()
        return ("updated", r.json()["data"]["attributes"]["extra"]["hashes"]["sha256"])

    upload_url = f"{WB_ROOT}/resources/{node_id}/providers/osfstorage/"
    params = {"kind": "file", "name": filename}
    with local.open("rb") as f:
        r = requests.put(upload_url, headers=headers, params=params, data=f, timeout=60)
    r.raise_for_status()
    return ("created", r.json()["data"]["attributes"]["extra"]["hashes"]["sha256"])


def main() -> int:
    load_dotenv()
    token = os.environ.get("OSF_TOKEN")
    node_id = os.environ.get("OSF_PROJECT_ID")
    if not token or not node_id:
        print("ERROR: OSF_TOKEN and OSF_PROJECT_ID must be set in .env", file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="*", help="filenames relative to docs/preregistrations/")
    parser.add_argument("--all", action="store_true", help="upload every .md and .yaml in docs/preregistrations/")
    args = parser.parse_args()

    if args.all:
        paths = sorted([p for p in PREREG_DIR.iterdir() if p.suffix in {".md", ".yaml"}])
    else:
        if not args.files:
            parser.error("pass filenames or --all")
        paths = [PREREG_DIR / f for f in args.files]

    missing = [p for p in paths if not p.exists()]
    if missing:
        for p in missing:
            print(f"ERROR: not found: {p}", file=sys.stderr)
        return 2

    existing = list_existing(node_id, token)
    print(f"OSF node {node_id}: {len(existing)} file(s) already present")
    print("-" * 70)
    for p in paths:
        action, remote_sha = upload_or_update(p, node_id, token, existing)
        print(f"  {action:9s}  {p.name:40s}  sha256={remote_sha[:12]}...")
    print("-" * 70)
    print(f"Done. See https://osf.io/{node_id}/files/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
