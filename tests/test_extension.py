"""Extension checks: manifest, files, JS syntax, vocabulary guardrails,
design tokens, and the view-model adapter (node tests + UI contract).
"""
import json
import os
import re
import subprocess
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(BASE, "extension")
REQUIRED = ("manifest.json", "api.js", "viewmodel.js", "background.js",
            "content.js", "sidebar.css", "popup.html", "popup.js")

# Product vocabulary: the system must never present these as findings.
BANNED = ("was unemployed", "is unemployed", "unemployment confirmed",
          "employment gap confirmed", "bad career history", "red flag candidate",
          "red flag", "employment gap")

# Raw pipeline leakage that must not reach recruiters.
BANNED_RAW = (r"conf \d", "EMPLOYMENT - conf", "Duration: June 26")


class TestExtension(unittest.TestCase):
    def test_files_present(self):
        for f in REQUIRED:
            self.assertTrue(os.path.isfile(os.path.join(EXT, f)), f)

    def test_manifest(self):
        with open(os.path.join(EXT, "manifest.json")) as fh:
            m = json.load(fh)
        self.assertEqual(m["manifest_version"], 3)
        self.assertIn("background", m)
        js = m["content_scripts"][0]["js"]
        self.assertIn("viewmodel.js", js)
        self.assertIn("content.js", js)
        self.assertIn("http://127.0.0.1:8000/*", m["host_permissions"])

    def test_js_syntax(self):
        node = shutil_which_node()
        self.assertTrue(node, "node required for JS syntax check")
        for f in ("api.js", "viewmodel.js", "background.js", "content.js", "popup.js"):
            p = subprocess.run([node, "--check", os.path.join(EXT, f)],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, f"{f}: {p.stderr}")

    def test_viewmodel_node(self):
        node = shutil_which_node()
        p = subprocess.run([node, os.path.join(EXT, "viewmodel.test.js")],
                           capture_output=True, text=True, cwd=BASE)
        self.assertEqual(p.returncode, 0, p.stderr or p.stdout)

    def test_document_relay(self):
        p = subprocess.run([shutil_which_node(), os.path.join(EXT, "background.test.js")],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr or p.stdout)

    def test_vocabulary(self):
        for f in ("content.js", "popup.js", "background.js", "viewmodel.js"):
            with open(os.path.join(EXT, f), encoding="utf-8") as fh:
                text = fh.read().lower()
            # the BANNED_CLAIMS denylist itself documents the guard; scan the rest
            text = re.sub(r"banned_claims\s*=\s*\[.*?\]", "", text, flags=re.S)
            for phrase in BANNED:
                self.assertNotIn(phrase, text, f"{f}: {phrase!r}")
            for pat in BANNED_RAW:
                self.assertIsNone(re.search(pat, text), f"{f}: {pat!r}")

    def test_design_tokens(self):
        with open(os.path.join(EXT, "sidebar.css"), encoding="utf-8") as fh:
            css = fh.read()
        for token in ("--status-high-attention", "--status-review",
                      "--status-clear", "--status-neutral"):
            self.assertIn(token, css, token)

    def test_view_contract(self):
        """UI consumes the view-model (tabs, cards, drawer, verbal confidence)."""
        with open(os.path.join(EXT, "content.js"), encoding="utf-8") as fh:
            js = fh.read()
        for marker in ("mapTimelineResultToRecruiterViewModel", "data-tab",
                       "rt-gap", "rt-rev", "rt-tl", "rt-evbox", "aria-selected",
                       "role=\"tablist\"", "role=\"tabpanel\""):
            self.assertIn(marker, js, marker)
        with open(os.path.join(EXT, "viewmodel.js"), encoding="utf-8") as fh:
            vm = fh.read()
        for marker in ("attentionRules", "minimumGapMonthsForHighAttention",
                       "minimumConfidenceForHighAttention", "presentationPriority",
                       "overallStatus", "highGaps",
                       "timelineEvents", "reviewItems"):
            self.assertIn(marker, vm, marker)


def shutil_which_node():
    import shutil
    return shutil.which("node")


if __name__ == "__main__":
    unittest.main()
