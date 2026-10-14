"""Download one explicitly chosen public text resource plus its full license.

Standard library only. No package installation, extraction, execution or mirroring.
The caller must verify that the intended use is permitted by the resource license.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import socket
import sys
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


MAX_BYTES = 2 * 1024 * 1024
EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".css", ".json", ".txt", ".md", ".html", ".svg"}


def public_https(url: str, *, resolve: bool = True) -> str:
    """Reject credentials, local addresses and non-HTTPS download/redirect URLs."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("Only public HTTPS URLs without credentials are accepted")
    if parts.query or parts.fragment:
        raise ValueError("Use a stable public raw URL without a query or fragment")
    if parts.port not in (None, 443):
        raise ValueError("Only the standard HTTPS port is accepted")
    hostname = parts.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith((".local", ".localhost", ".internal")):
        raise ValueError("Local network hosts are not public resources")
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise ValueError("Non-public IP address rejected")
    if resolve:
        addresses = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError("Host must resolve only to public addresses")
    return url


class PublicRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_https(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str) -> tuple[bytes, str]:
    public_https(url)
    request = Request(url, headers={"User-Agent": "ui-reference-library/1.0", "Accept": "text/plain,application/json,*/*;q=0.1"})
    with build_opener(PublicRedirects()).open(request, timeout=30) as response:
        final_url = public_https(response.geturl())
        data = response.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise ValueError("Resource must be nonempty and no larger than 2 MiB")
    text = data.decode("utf-8-sig")
    if "\x00" in text:
        raise ValueError("Binary resources are not accepted by this text downloader")
    # A raw-source URL silently redirected to a login/error page is not source code.
    if re.search(r"<!doctype\s+html|<html\b", text[:1024], re.I):
        raise ValueError("Received a full HTML document; use the public raw-source URL")
    return data, final_url


def output_paths(workspace: str, dest: str, filename: str, kind: str) -> tuple[Path, Path, Path]:
    root = Path(workspace).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Workspace must be an existing directory")
    relative = Path(dest)
    if relative.is_absolute() or relative.drive or ".." in relative.parts:
        raise ValueError("Destination must be a relative workspace subdirectory")
    target_dir = (root / relative).resolve()
    if target_dir == root or not target_dir.is_relative_to(root):
        raise ValueError("Destination must remain in a workspace subdirectory")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", filename):
        raise ValueError("Filename must be a simple ASCII basename")
    if Path(filename).suffix.lower() not in EXTENSIONS:
        raise ValueError("Only supported source/text file extensions are accepted")
    source = target_dir / filename
    license_path = source if kind == "license" else target_dir / (filename + ".LICENSE.txt")
    metadata = target_dir / (filename + ".source.json")
    if any(path.exists() or path.is_symlink() for path in {source, license_path, metadata}):
        raise FileExistsError("Refusing to overwrite an existing reference; choose a new destination")
    return source, license_path, metadata


def github_provenance(url: str) -> dict | None:
    """Record a raw GitHub revision; never label a moving branch as a commit."""
    parsed = urlsplit(url)
    segments = parsed.path.strip("/").split("/")
    if parsed.hostname != "raw.githubusercontent.com" or len(segments) < 4:
        return None
    owner, repo, revision = segments[:3]
    return {
        "repository": f"https://github.com/{owner}/{repo}",
        "revision": revision,
        "commit_sha": revision.lower() if re.fullmatch(r"[0-9a-fA-F]{40}", revision) else None,
        "path": "/".join(segments[3:]),
    }


def download(args: argparse.Namespace) -> dict:
    source, license_path, metadata = output_paths(args.workspace, args.dest, args.filename, args.kind)
    public_https(args.source_page, resolve=False)
    public_https(args.license_url, resolve=False)
    if not args.license_name.strip():
        raise ValueError("Supply the license name verified for this resource")
    if args.kind == "license" and args.url != args.license_url:
        raise ValueError("For a license reference, --url and --license-url must match")
    source_bytes, resolved_source = fetch(args.url)
    if args.kind == "license":
        license_bytes, resolved_license = source_bytes, resolved_source
    else:
        license_bytes, resolved_license = fetch(args.license_url)
    record = {
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "source_page": args.source_page,
        "requested_url": args.url,
        "resolved_url": resolved_source,
        "github": github_provenance(resolved_source),
        "file": source.name,
        "bytes": len(source_bytes),
        "sha256": hashlib.sha256(source_bytes).hexdigest(),
        "purpose": args.purpose,
        "kind": args.kind,
        "license": {
            "name": args.license_name,
            "requested_url": args.license_url,
            "resolved_url": resolved_license,
            "github": github_provenance(resolved_license),
            "file": license_path.name,
            "sha256": hashlib.sha256(license_bytes).hexdigest(),
        },
        "execution": "none",
        "review_note": "Download records provenance only; intended use and license must be reviewed by the caller.",
    }
    source.parent.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        entries = [(source, source_bytes)]
        if license_path != source:
            entries.append((license_path, license_bytes))
        entries.append((metadata, (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8")))
        for path, contents in entries:
            with path.open("xb") as stream:
                created.append(path)
                stream.write(contents)
    except Exception:
        # Remove only files this invocation created, never pre-existing references.
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--dest", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--filename", required=True)
    parser.add_argument("--source-page", required=True)
    parser.add_argument("--license-name", required=True)
    parser.add_argument("--license-url", required=True)
    parser.add_argument("--kind", choices=("source", "license"), default="source")
    parser.add_argument("--purpose", choices=("reference", "integrate"), required=True)
    try:
        record = download(parser.parse_args())
    except (OSError, ValueError) as exc:
        print(f"Download failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
