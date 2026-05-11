#!/usr/bin/env python3
"""
Regenerate index.json in the profiles S3 bucket.

Usage: python3 scripts/index.py

Reads AWS credentials from the environment (AWS_ACCESS_KEY_ID,
AWS_SECRET_ACCESS_KEY) or any other boto3-supported credential source.
"""

import json
import plistlib
import sys
import boto3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

BUCKET = "profiles.cyberduck.io"
INDEX_KEY = "index.json"
SUFFIX = ".cyberduckprofile"

s3 = boto3.client("s3")


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
            "protocol": d.get("Protocol", ""),
            "vendor": d.get("Vendor", ""),
            "description": d.get("Description", ""),
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
