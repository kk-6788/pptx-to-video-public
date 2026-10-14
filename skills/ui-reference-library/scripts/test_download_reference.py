"""Offline behavior checks: python -B scripts/test_download_reference.py."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import download_reference as downloader


class DownloadChecks(unittest.TestCase):
    def test_github_commit_and_file_hash_are_distinct(self):
        commit = "a" * 40
        pinned = downloader.github_provenance(f"https://raw.githubusercontent.com/owner/repo/{commit}/icons/a.svg")
        self.assertEqual(pinned["commit_sha"], commit)
        self.assertEqual(pinned["path"], "icons/a.svg")
        branch = downloader.github_provenance("https://raw.githubusercontent.com/owner/repo/main/LICENSE.md")
        self.assertIsNone(branch["commit_sha"])
        self.assertIsNone(downloader.github_provenance("https://example.com/asset.svg"))

    def args(self, root):
        return argparse.Namespace(
            workspace=root, dest="vendor/chosen", filename="button.css", kind="source",
            url="https://example.com/button.css", source_page="https://example.com/button",
            license_url="https://example.com/LICENSE.md", license_name="MIT", purpose="integrate",
        )

    def test_disallow_nonpublic_or_credential_urls(self):
        for url in ("http://example.com/a", "file:///tmp/a", "https://localhost/a",
                    "https://127.0.0.1/a", "https://[::1]/a", "https://10.1.2.3/a",
                    "https://user:password@example.com/a", "https://example.com/a?token=secret"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                downloader.public_https(url, resolve=False)

    def test_disallow_private_dns_resolution(self):
        with patch.object(downloader.socket, "getaddrinfo", return_value=[(None, None, None, None, ("192.168.1.2", 443))]):
            with self.assertRaises(ValueError):
                downloader.public_https("https://example.com/code.css")

    def test_destination_stays_in_workspace(self):
        with tempfile.TemporaryDirectory() as root:
            for dest in ("../escape", ".", str(Path(root).anchor)):
                with self.subTest(dest=dest), self.assertRaises(ValueError):
                    downloader.output_paths(root, dest, "safe.css", "source")

    def test_no_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / "vendor/chosen"
            folder.mkdir(parents=True)
            file = folder / "button.css"
            file.write_text("existing", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                downloader.download(self.args(root))
            self.assertEqual(file.read_text(encoding="utf-8"), "existing")

    def test_hash_full_license_and_no_execution(self):
        source, license_text = b"button { color: red; }", b"Complete test license\nCopyright test\n"
        with tempfile.TemporaryDirectory() as root, patch.object(downloader, "fetch", side_effect=[(source, "https://example.com/button.css"), (license_text, "https://example.com/LICENSE.md")]):
            record = downloader.download(self.args(root))
            output = Path(root) / "vendor/chosen"
            self.assertEqual((output / "button.css").read_bytes(), source)
            self.assertEqual((output / "button.css.LICENSE.txt").read_bytes(), license_text)
            saved = json.loads((output / "button.css.source.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["sha256"], hashlib.sha256(source).hexdigest())
            self.assertEqual(record["execution"], "none")

    def test_license_failure_does_not_leave_unlicensed_code(self):
        with tempfile.TemporaryDirectory() as root, patch.object(downloader, "fetch", side_effect=[(b"a{}", "https://example.com/button.css"), OSError("network")]):
            with self.assertRaises(OSError):
                downloader.download(self.args(root))
            self.assertFalse((Path(root) / "vendor").exists())

    def test_license_kind_requires_matching_url(self):
        with tempfile.TemporaryDirectory() as root:
            args = self.args(root)
            args.kind = "license"
            with self.assertRaises(ValueError):
                downloader.download(args)

    def test_binary_filename_not_allowed(self):
        with tempfile.TemporaryDirectory() as root:
            for filename in ("payload.exe", "../outside.css", "x:stream.css"):
                with self.subTest(filename=filename), self.assertRaises(ValueError):
                    downloader.output_paths(root, "vendor/chosen", filename, "source")


if __name__ == "__main__":
    unittest.main(verbosity=2)
