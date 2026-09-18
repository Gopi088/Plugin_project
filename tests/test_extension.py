"""Extension integration checks: manifest validity, file presence,
JS syntax (node --check), and vocabulary guardrails for reviewer-facing text.
"""
import json
import os
import subprocess
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(BASE, "extension")
REQUIRED = ("manifest.json", "api.js", "background.js", "content.js",
            "sidebar.css", "popup.html", "popup.js")


class TestExtension(unittest.TestCase):
    def test_files_present(self):
        for f in REQUIRED:
            self.assertTrue(os.path.isfile(os.path.join(EXT, f)), f)

    def test_manifest(self):
        with open(os.path.join(EXT, "manifest.json")) as fh:
            m = json.load(fh)
        self.assertEqual(m["manifest_version"], 3)
        self.assertIn("background", m)
        self.assertTrue(m["content_scripts"])
        self.assertIn("http://127.0.0.1:8000/*", m["host_permissions"])

    def test_js_syntax(self):
        node = shutil_which_node()
        self.assertTrue(node, "node required for JS syntax check")
        for f in ("api.js", "background.js", "content.js", "popup.js"):
            p = subprocess.run([node, "--check", os.path.join(EXT, f)],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, f"{f}: {p.stderr}")

    def test_no_unemployed_claim(self):
        for f in ("content.js", "popup.js", "background.js"):
            with open(os.path.join(EXT, f), encoding="utf-8") as fh:
                text = fh.read().lower()
            self.assertNotIn("unemploy", text, f)


def shutil_which_node():
    import shutil
    return shutil.which("node")


if __name__ == "__main__":
    unittest.main()
