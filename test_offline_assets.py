"""Offline-only checks for the optional, bundled browser interface.

Run with: python -B -m unittest -v test_offline_assets
No application imports, installed browser, credentials, or network are used.
"""
import hashlib
import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"


class AssetTags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []
        self.scripts = []

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "script" and attrs.get("src"):
            self.references.append(attrs["src"])
            self.scripts.append(attrs["src"])
        if tag == "link" and attrs.get("href"):
            if set(attrs.get("rel", "").split()) & {
                "stylesheet", "preload", "modulepreload", "icon", "preconnect", "dns-prefetch"
            }:
                self.references.append(attrs["href"])
        if tag in {"img", "iframe", "source", "video", "audio", "embed"} and attrs.get("src"):
            self.references.append(attrs["src"])


class OfflineAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(
            (ROOT / "packaging/vendor-assets.json").read_text(encoding="utf-8")
        )
        cls.assets = [
            asset for package in cls.manifest["packages"] for asset in package["files"]
        ]
        cls.contents = {}
        for asset in cls.assets:
            path = (ROOT / asset["path"]).resolve()
            if path.is_file():
                cls.contents[path] = path.read_bytes()
        cls.templates = {
            name: (ROOT / name).read_text(encoding="utf-8")
            for name in ("templates/index.html", "templates/dashboard.html")
        }
        cls.tags = {}
        for name, html in cls.templates.items():
            parser = AssetTags()
            parser.feed(html)
            cls.tags[name] = parser
        cls.style_path = STATIC / "style.css"
        cls.style = cls.style_path.read_text(encoding="utf-8")

    def local_reference(self, parent, value):
        value = value.strip().strip("'\"")
        if value.startswith(("data:", "#")):
            return None
        parsed = urlsplit(value)
        self.assertFalse(parsed.scheme or parsed.netloc, f"External dependency: {value}")
        self.assertTrue(parsed.path, f"Empty dependency: {value}")
        decoded = unquote(parsed.path)
        target = (
            ROOT / decoded.lstrip("/")
            if decoded.startswith("/")
            else parent.parent / decoded
        ).resolve()
        self.assertTrue(target.is_relative_to(STATIC.resolve()), str(target))
        self.assertTrue(target.is_file(), f"Missing local dependency: {target}")
        return target

    def test_manifest_files_are_present_and_hash_locked(self):
        self.assertEqual(self.manifest["schema_version"], 1)
        paths = [asset["path"] for asset in self.assets]
        self.assertEqual(len(paths), len(set(paths)), "Duplicate manifest destinations")
        for package in self.manifest["packages"]:
            self.assertRegex(package["version"], r"^\d+\.\d+\.\d+$")
            if "archive" in package:
                self.assertTrue(package["archive"]["url"].startswith("https://registry.npmjs.org/"))
                self.assertRegex(package["archive"]["sha256"], r"^[0-9a-f]{64}$")
                self.assertTrue(package["archive"]["sha512_integrity"].startswith("sha512-"))
            for asset in package["files"]:
                with self.subTest(path=asset["path"]):
                    path = (ROOT / asset["path"]).resolve()
                    self.assertTrue(path.is_relative_to((STATIC / "vendor").resolve()))
                    self.assertIn(path, self.contents)
                    content = self.contents[path]
                    self.assertEqual(len(content), asset["bytes"])
                    self.assertEqual(hashlib.sha256(content).hexdigest(), asset["sha256"])
                    if "url" in asset:
                        self.assertTrue(asset["url"].startswith("https://cdn.datatables.net/"))

    def test_every_package_has_its_original_license_and_notice(self):
        notice = (ROOT / self.manifest["notice"]).read_text(encoding="utf-8")
        for package in self.manifest["packages"]:
            with self.subTest(package=package["name"]):
                self.assertEqual(package["license"], "MIT")
                license_files = [f["path"] for f in package["files"] if f["role"] == "license"]
                self.assertIn(package["license_path"], license_files)
                text = self.contents[(ROOT / package["license_path"]).resolve()].decode("utf-8")
                self.assertIn("Copyright", text)
                self.assertIn("Permission is hereby granted", text)
                self.assertIn('THE SOFTWARE IS PROVIDED "AS IS"', text)
                self.assertIn(package["name"], notice)
                self.assertIn(package["license_path"], notice)

    def test_all_template_autoloads_are_local(self):
        for name, html in self.templates.items():
            with self.subTest(template=name):
                self.assertNotRegex(
                    html, r"(?i)(?:https?:)?//(?:cdn\.jsdelivr\.net|cdn\.datatables\.net|cdnjs\.cloudflare\.com|unpkg\.com)"
                )
                for reference in self.tags[name].references:
                    self.assertTrue(reference.startswith("/static/"), reference)
                    self.local_reference(ROOT / name, reference)
        for entry in self.manifest["template_references"]:
            self.assertNotIn(entry["original_url"], self.templates[entry["template"]])
            self.assertEqual(self.templates[entry["template"]].count(entry["local_url"]), 1)

    def test_all_runtime_assets_are_referenced(self):
        observed = set()
        for parser in self.tags.values():
            observed.update(url for url in parser.references if url.startswith("/static/vendor/"))
        html = self.templates["templates/dashboard.html"]
        language_urls = re.findall(r"language\s*:\s*\{\s*url\s*:\s*['\"]([^'\"]+)['\"]", html)
        self.assertEqual(len(language_urls), 1)
        observed.update(language_urls)
        expected = {"/" + a["path"] for a in self.assets if a["role"] == "asset"}
        self.assertEqual(observed, expected)
        declared = {entry["local_url"] for entry in self.manifest["template_references"]}
        self.assertEqual(observed, declared)

    def test_dashboard_dependency_order_is_preserved(self):
        names = [Path(url).name for url in self.tags["templates/dashboard.html"].scripts]
        self.assertEqual(names, [
            "bootstrap.bundle.min.js", "jquery.min.js", "jquery.dataTables.min.js",
            "dataTables.bootstrap5.min.js", "dataTables.responsive.min.js",
            "responsive.bootstrap5.min.js",
        ])

    def test_css_and_source_map_references_resolve_offline(self):
        texts = {self.style_path: self.style}
        for path, content in self.contents.items():
            if path.suffix in {".css", ".js"}:
                texts[path] = content.decode("utf-8")
        for path, text in texts.items():
            with self.subTest(file=str(path.relative_to(ROOT))):
                for reference in re.findall(r"sourceMappingURL=([^\s*]+)", text):
                    self.local_reference(path, reference)
                if path.suffix == ".css":
                    for reference in re.findall(r"url\(\s*([^)]*?)\s*\)", text):
                        self.local_reference(path, reference)
                    for reference in re.findall(r"@import\s+['\"]([^'\"]+)['\"]", text):
                        self.local_reference(path, reference)

    def test_source_maps_embed_or_bundle_their_sources(self):
        for path, content in self.contents.items():
            if path.suffix != ".map":
                continue
            data = json.loads(content)
            sources = data["sources"]
            embedded = data.get("sourcesContent", [])
            for index, source in enumerate(sources):
                if index >= len(embedded) or embedded[index] is None:
                    with self.subTest(map=path.name, source=source):
                        self.local_reference(path, data.get("sourceRoot", "") + source)

    def test_chinese_language_file_remains_valid(self):
        entries = [
            entry for entry in self.manifest["template_references"]
            if entry["kind"] == "language"
        ]
        self.assertEqual(len(entries), 1)
        path = self.local_reference(ROOT / entries[0]["template"], entries[0]["local_url"])
        language = json.loads(self.contents[path])
        self.assertTrue({"search", "paginate", "emptyTable", "info", "lengthMenu"} <= language.keys())
        self.assertTrue({"first", "last", "next", "previous"} <= language["paginate"].keys())


if __name__ == "__main__":
    unittest.main()
