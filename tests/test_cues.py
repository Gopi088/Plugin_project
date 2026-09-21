"""Config tests: all pipeline vocabularies live in backend/data/cues.json
(and skills.json) — tuning must never require code changes."""
import json
import os
import re
import unittest

from backend.cues import load, clear_cache

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REQUIRED_KEYS = ("section_headers", "company_suffixes_regex", "title_words_regex",
                 "degree_words_regex", "job_family_words_regex", "internship_words",
                 "nav_terms_regex", "project_field_labels_regex",
                 "present_words_regex", "stop_words")


class TestCues(unittest.TestCase):
    def test_keys_present(self):
        c = load()
        for k in REQUIRED_KEYS:
            self.assertIn(k, c, k)
        for k in ("EXPERIENCE", "EDUCATION", "PROJECTS", "SKILLS"):
            self.assertIn(k, c["section_headers"], k)

    def test_fragments_compile(self):
        c = load()
        for k in [k for k in REQUIRED_KEYS if k.endswith("_regex")]:
            for frag in c[k]:
                re.compile(frag)

    def test_skills_shared(self):
        with open(os.path.join(BASE, "backend", "data", "skills.json")) as fh:
            skills = json.load(fh)
        self.assertGreater(len(skills), 20)
        for must in ("python", "java", "aws", "docker", "kubernetes"):
            self.assertIn(must, skills)

    def test_env_override(self):
        import tempfile
        clear_cache()
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
                base = load()
                custom = dict(base, internship_words=["trainee"])
                json.dump(custom, fh)
                path = fh.name
            os.environ["RT_CUES_PATH"] = path
            clear_cache()
            self.assertEqual(load()["internship_words"], ["trainee"])
        finally:
            os.environ.pop("RT_CUES_PATH", None)
            clear_cache()
            load()


if __name__ == "__main__":
    unittest.main()
