"""Publish organizer originals + per-photo data to a private S3-compatible bucket.

Run with operator credentials, not inside a shared editor. No automatic
overwriting, public ACL or modification of application/user photo objects.
Uses the same AWS endpoint/key environment conventions as boto3.
"""
import argparse
import hashlib
import json
import mimetypes
import tempfile
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

FILES = {
    "doc-1795639519.zip": "489abe2497e1282d166e56197ff0f61c033ecbf7d4545ad9c57f757eb20302ce",
    "doc-1795639569.zip": "7f343037479cac7340dbc9f912a37713d4b7c2a4a7e6dac0bd1955ab409c56ed",
    "doc-1795639713.docx": "586c72843958e698636ce930e559a43b5e29e8cc5ebbc0b8ae2c0ec2f2ae9033",
}


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def run(source, client):
    bucket, prefix = "mgts-hackathon", "final-2026/"
    prepared = source / "prepared"
    manifest = prepared / "final-materials.json"
    entries, sources = [], []
    for name, expected in FILES.items():
        path = source / name
        if digest(path) != expected:
            raise ValueError(f"organizer artifact digest mismatch: {name}")
        entries.append(("originals/" + name, path, expected))
        sources.append(dict(url="https://lk.studchamp.mgts.ru/storage/docs/" + name,
                            key=prefix+"originals/"+name, sha256=expected, bytes=path.stat().st_size))
    rows = json.loads(manifest.read_text())["samples"]
    for row in rows:
        rel = row["image_path"]
        path = (prepared / rel).resolve()
        if Path(rel).is_absolute() or ".." in Path(rel).parts or not path.is_relative_to(prepared.resolve()):
            raise ValueError("unsafe photo path")
        if digest(path) != row["sha256"]:
            raise ValueError(f"photo digest mismatch: {rel}")
        entries.append((rel, path, row["sha256"]))
    if len(rows) != 62 or len({x[0] for x in entries}) != len(entries):
        raise ValueError("unexpected input set")
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("404", "NoSuchBucket", "NotFound"):
            raise
        client.create_bucket(Bucket=bucket)
    added = 0
    with tempfile.TemporaryDirectory() as td:
        prov = Path(td) / "SOURCES.json"
        prov.write_text(json.dumps({"originals": sources, "manifest_sha256": digest(manifest)},indent=2)+"\n")
        # Manifest is the publish marker: populate images before publishing it.
        entries.extend([("SOURCES.json", prov, digest(prov)), ("final-materials.json", manifest, digest(manifest))])
        for rel, path, sha in entries:
            key = prefix+rel
            try:
                existing = client.head_object(Bucket=bucket, Key=key)
                if existing["ContentLength"] != path.stat().st_size:
                    raise ValueError(f"existing object differs: {key}")
            except ClientError as e:
                if e.response["Error"]["Code"] not in ("404","NoSuchKey","NotFound"):
                    raise
                with path.open("rb") as stream:
                    client.put_object(Bucket=bucket, Key=key, Body=stream, IfNoneMatch="*",
                        Metadata={"sha256":sha}, ContentType=mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                added+=1
            body=client.get_object(Bucket=bucket,Key=key)["Body"]
            try:
                h=hashlib.sha256()
                for chunk in body.iter_chunks(chunk_size=1024*1024): h.update(chunk)
                if h.hexdigest()!=sha: raise ValueError(f"remote content differs: {key}")
            finally:
                body.close()
    print(f"s3://{bucket}/{prefix} photos={len(rows)} organizer_originals={len(FILES)} verified={len(entries)} added={added}")


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("source",type=Path); p.add_argument("--endpoint",required=True)
    args=p.parse_args()
    run(args.source,boto3.client("s3",endpoint_url=args.endpoint,region_name="us-east-1",config=Config(signature_version="s3v4",s3={"addressing_style":"path"})))
