#!/usr/bin/env python3
"""Publish Conductor release binaries to GitHub Releases using GitHub API."""
import os
import json
import urllib.request
import urllib.error
from pathlib import Path

REPO = "gabelmz/conductor"
TAG = "v2.7.0"
TITLE = "v2.7.0: Domain Router Architecture, Dataset Pipeline & Context Menu Engine"
BODY = """# Conductor v2.7.0 Release

### Key Highlights
- **Domain Router Architecture**: refactored 30+ FastAPI routes into clean domain-bound router modules (`router_registry.py`).
- **Local Dataset Store & WAL Checkpoints**: automated raw-to-staging dataset storage, view caching, and SQLite WAL checkpoint manager.
- **Unified Search Engine**: parallel cross-channel search spanning Catalog, Asana, Keepa, and Supabase with coverage gap analysis.
- **Context Menu Customization**: user-definable page context menus and custom action handlers (`page-context-menu.js`).
- **Input Lag & Task Coalescing**: LIFO Action Queue (`action-queue.js`) with request abort controller cancellation.
"""

DIST_DIR = Path(r"C:\Users\GabeMaher\Documents\Development\Vaults\luminize-vault\Development\apps\conductor\dist")
TOKEN_PATH = Path(r"C:\Users\GabeMaher\Documents\Development\Vaults\luminize-vault\Development\apps\conductor\desktop\gh-token")

def main():
    if not TOKEN_PATH.exists():
        print("ERROR: gh-token file missing")
        return 1
    token = TOKEN_PATH.read_text(encoding="utf-8").strip()

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Conductor-Publisher",
    }

    # 1. Get existing releases or create a new one
    url = f"https://api.github.com/repos/{REPO}/releases"
    req = urllib.request.Request(url, headers=headers)
    releases = []
    try:
        with urllib.request.urlopen(req) as resp:
            releases = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"Error listing releases: {exc}")

    existing = next((r for r in releases if r.get("tag_name") == TAG), None)
    if existing:
        release_id = existing["id"]
        upload_url = existing["upload_url"].split("{")[0]
        print(f"Found existing release ID {release_id} for tag {TAG}")
    else:
        payload = {
            "tag_name": TAG,
            "target_commitish": "main",
            "name": TITLE,
            "body": BODY,
            "draft": False,
            "prerelease": False,
        }
        create_req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={**headers, "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(create_req) as resp:
                created = json.loads(resp.read().decode("utf-8"))
                release_id = created["id"]
                upload_url = created["upload_url"].split("{")[0]
                print(f"Created new GitHub release ID {release_id} for tag {TAG}")
        except Exception as exc:
            print(f"Failed to create release: {exc}")
            if hasattr(exc, "read"):
                print(exc.read().decode("utf-8"))
            return 1

    # 2. Upload release assets (single-file NSIS installer + blockmap + latest.yml)
    assets_to_upload = [
        ("Conductor-Setup-2.7.0.exe", "application/octet-stream"),
        ("Conductor-Setup-2.7.0.exe.blockmap", "application/octet-stream"),
        ("latest.yml", "text/yaml"),
    ]

    for filename, mime_type in assets_to_upload:
        file_path = DIST_DIR / filename
        if not file_path.exists():
            print(f"Skipping missing asset: {filename}")
            continue

        print(f"Uploading asset {filename} ({file_path.stat().st_size} bytes)...")
        data = file_path.read_bytes()
        upload_req_url = f"{upload_url}?name={filename}"
        asset_headers = {
            **headers,
            "Content-Type": mime_type,
            "Content-Length": str(len(data)),
        }
        u_req = urllib.request.Request(upload_req_url, data=data, headers=asset_headers, method="POST")
        try:
            with urllib.request.urlopen(u_req) as resp:
                asset_res = json.loads(resp.read().decode("utf-8"))
                print(f"Successfully uploaded {filename} (id={asset_res.get('id')})")
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8")
            if "already_exists" in err_body:
                print(f"Asset {filename} already exists on release.")
            else:
                print(f"Failed uploading {filename}: {exc} - {err_body}")
        except Exception as exc:
            print(f"Error uploading {filename}: {exc}")

    print("Release publishing process complete.")
    return 0

if __name__ == "__main__":
    main()
