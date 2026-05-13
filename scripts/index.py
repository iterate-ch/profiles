#!/usr/bin/env python3
"""
Regenerate index.json in the profiles S3 bucket.

Usage: python3 scripts/index.py

Reads AWS credentials from the environment (AWS_ACCESS_KEY_ID,
AWS_SECRET_ACCESS_KEY) or any other boto3-supported credential source.
"""

import base64
import binascii
import io
import json
import plistlib
import sys
import boto3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from PIL import Image

BUCKET = "profiles.cyberduck.io"
INDEX_KEY = "index.json"
SUFFIX = ".cyberduckprofile"

s3 = boto3.client("s3")


def _scale_thumbnail(disk: str) -> str:
    """Scale a Base64-encoded TIFF to 32×32 px and return as a Base64-encoded PNG."""
    try:
        decoded = base64.b64decode(disk, validate=False)
    except binascii.Error as e:
        print(f"base64 decode failed for type={type(disk).__name__} len={len(disk)} repr={repr(disk[:80])}", file=sys.stderr)
        return None
    with Image.open(io.BytesIO(decoded)) as img:
        img = img.resize((32, 32), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()
    return None


def _fetch(key, version_id):
    body = s3.get_object(Bucket=BUCKET, Key=key, VersionId=version_id)["Body"].read()
    try:
        return plistlib.loads(body)
    except plistlib.InvalidFileException:
        print(f"Failed to parse {key} ({version_id})", file=sys.stderr)
        return None


def main():
    # Group all versions by key, preserving per-version ETag/LastModified
    paginator = s3.get_paginator("list_object_versions")
    versions_by_key: dict[str, list] = {}
    for page in paginator.paginate(Bucket=BUCKET):
        for v in page.get("Versions", []):
            if v["Key"].endswith(SUFFIX):
                versions_by_key.setdefault(v["Key"], []).append(v)

    # Fetch the latest version's plist content for each key (for metadata).
    # Keys whose current state is a delete marker have no IsLatest version — skip them.
    latest_by_key = {}
    for key, vs in versions_by_key.items():
        latest = next((v for v in vs if v["IsLatest"]), None)
        if latest is not None:
            latest_by_key[key] = latest

    parsed = {}
    with ThreadPoolExecutor(max_workers=32) as pool:
        futures = {
            pool.submit(_fetch, key, obj["VersionId"]): key
            for key, obj in latest_by_key.items()
        }
        for future in as_completed(futures):
            key = futures[future]
            d = future.result()
            if d is not None:
                parsed[key] = d

    profiles = []
    for key in sorted(versions_by_key):
        if key not in parsed:
            continue
        d = parsed[key]
        # Versions sorted newest-first; IsLatest version carries top-level metadata
        versions = sorted(
            versions_by_key[key],
            key=lambda v: v["LastModified"],
            reverse=True,
        )
        entry = {
            "filename": key,
            "protocol": d.get("Protocol", None),
            "vendor": d.get("Vendor", None),
            "description": d.get("Description", None),
            "help": d.get("Help", None),
            "thumbnail": _scale_thumbnail(d["Disk"]) if "Disk" in d else None,
            "versions": [
                {
                    # ETag is the MD5 hex digest for non-multipart uploads
                    "checksum": v["ETag"].strip('"'),
                    "modified": v["LastModified"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "version_id": v["VersionId"],
                    "latest": v["IsLatest"],
                }
                for v in versions
            ],
        }
        profiles.append(entry)

    index = {
        "version": "1.0",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "profiles": profiles,
    }

    s3.put_object(
        Bucket=BUCKET,
        Key=INDEX_KEY,
        Body=json.dumps(index, ensure_ascii=False).encode(),
        ContentType="application/json",
    )

    print(f"Wrote {INDEX_KEY} with {len(profiles)} profiles")


if __name__ == "__main__":
    sys.exit(main())
