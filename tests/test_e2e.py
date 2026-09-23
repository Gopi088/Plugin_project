"""End-to-end tests: real PDFs through the pipeline + live HTTP API."""
import base64
import json
import os
import subprocess
import time
import tempfile
import unittest
import urllib.request

from backend.pipeline_context import PipelineContext
from backend.pipeline import runner

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOPAL = os.path.join(BASE, "dataset", "resumes", "GopalPrasad K.pdf")
PARDHA_FILE = os.path.join(BASE, "dataset", "resumes", "Pardhasaradhi Reddy-resume.pdf")
PARDHA_TEXT = (
    "Pardha Fresher\n"
    "PROFESSIONAL SUMMARY\n"
    "CS undergraduate.\n"
    "PROJECTS\n"
    "App One\n"
    "- built x.\n"
    "EDUCATION\n"
    "B.Tech, Data Science | 9.5 CGPA\n"
)


class TestE2EResumes(unittest.TestCase):
    def _run(self, path=None, text=None):
        if path and os.path.isfile(path):
            with open(path, "rb") as fh:
                raw = fh.read()
            ctx = PipelineContext("e2e", os.path.basename(path), raw_bytes=raw)
        else:
            ctx = PipelineContext("e2e", "pardha.txt", raw_text=text or PARDHA_TEXT)
        runner.run(ctx)
        return ctx.recruiter_output

    def test_gopal_timeline(self):
        dto = self._run(path=GOPAL)
        self.assertEqual(len(dto["timeline"]), 3)
        starts = sorted(e["start"] for e in dto["timeline"])
        self.assertEqual(starts, ["2020-01", "2022-07", "2025-05"])
        gaps = sorted(g["months"] for g in dto["gaps"] if g["state"] == "POTENTIAL_GAP")
        self.assertEqual(gaps, [2])
        self.assertEqual(dto["gaps"][0]["evidence"]["coverage_scope"], "employment")

    def test_pardha_insufficient(self):
        dto = self._run(path=PARDHA_FILE, text=PARDHA_TEXT)
        self.assertEqual(dto["timeline"], [])
        self.assertEqual([g["state"] for g in dto["gaps"]], ["INSUFFICIENT_EVIDENCE"])


class TestAPI(unittest.TestCase):
    PORT = 18097
    srv = None

    @classmethod
    def setUpClass(cls):
        cls.temp_db = tempfile.TemporaryDirectory()
        cls.srv = subprocess.Popen(
            ["venv/bin/python", "backend/server.py", "--port", str(cls.PORT),
             "--db", os.path.join(cls.temp_db.name, "test.db")],
            cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{cls.PORT}/health", timeout=2)
                return
            except Exception:
                time.sleep(0.5)
        cls.tearDownClass()
        raise RuntimeError("test server did not start")

    @classmethod
    def tearDownClass(cls):
        if cls.srv:
            cls.srv.terminate()
            try:
                cls.srv.wait(timeout=10)
            except Exception:
                cls.srv.kill()
            for f in (cls.srv.stdout, cls.srv.stderr):
                try:
                    if f:
                        f.close()
                except Exception:
                    pass

        if hasattr(cls, "temp_db"):
            cls.temp_db.cleanup()

    def _api(self, path, payload=None):
        url = f"http://127.0.0.1:{self.PORT}{path}"
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=60).read())

    def test_submit_status_timeline_evidence_feedback(self):
        with open(os.path.join(BASE, "dataset/resumes/Abhishek Kumar Singh.pdf"), "rb") as fh:
            raw = fh.read()
        sub = self._api("/api/documents", {"filename": "g.pdf",
                                           "content_b64": base64.b64encode(raw).decode()})
        doc = sub["doc_id"]
        st = self._api(f"/api/documents/{doc}/status")
        self.assertEqual(len(st["stages"]), 12)
        tl = self._api(f"/api/documents/{doc}/timeline")
        self.assertEqual(len(tl["timeline"]), 4)
        gid = [g["id"] for g in tl["gaps"] if g["state"] == "POTENTIAL_GAP"][0]
        ev = self._api(f"/api/documents/{doc}/evidence?gap_id={gid}")
        self.assertTrue(ev["chain"]["links"])
        stages = self._api(f"/api/documents/{doc}/stages")
        self.assertEqual(len(stages["stages"]), 12)
        fb = self._api(f"/api/documents/{doc}/feedback",
                       {"dismissed_gap_ids": [gid], "overrides": [], "notes": "t"})
        self.assertTrue(fb["ok"])
        tl2 = self._api(f"/api/documents/{doc}/timeline")
        by_id = {g["id"]: g["state"] for g in tl2["gaps"]}
        self.assertEqual(by_id[gid], "DISMISSED_GAP")

    def test_abhishek_source_api(self):
        with open(os.path.join(BASE, "dataset", "resumes", "Abhishek Kumar Singh.pdf"), "rb") as fh:
            raw = fh.read()
        sub = self._api("/api/documents", {"filename": "Abhishek.pdf",
                                           "content_b64": base64.b64encode(raw).decode()})
        doc = sub["doc_id"]
        dto = self._api(f"/api/documents/{doc}/timeline")
        self.assertEqual([(g["start"], g["end"], g["months"]) for g in dto["gaps"]],
                         [("2018-08", "2018-09", 2)])
        education = next(e for e in dto["timeline"] if e["type"] == "EDUCATION")
        ev = self._api(f"/api/documents/{doc}/evidence?event_id={education['id']}")
        self.assertEqual(ev["source"]["dates"][0]["page"], 2)
        page = self._api(f"/api/documents/{doc}/source-page?page=2")
        self.assertTrue(page["image"].startswith("data:image/png;base64,"))
        with self.assertRaises(urllib.error.HTTPError) as err:
            self._api(f"/api/documents/{doc}/source-page?page=0")
        self.assertEqual(err.exception.code, 400)

    def test_notes_and_visibility_survive_http_reanalysis(self):
        payload = {"filename":"notes.txt", "text":"WORK EXPERIENCE\nEngineer, Alpha Ltd Jan 2020 – Dec 2021"}
        doc = self._api("/api/documents", payload)["doc_id"]
        dto = self._api(f"/api/documents/{doc}/timeline")
        event = dto["timeline"][0]["id"]
        notes = self._api(f"/api/documents/{doc}/notes", {"id":"http-note", "author":"Recruiter", "text":"Check dates"})
        self._api(f"/api/documents/{doc}/state", {"target_id":event,"reviewed":True})
        self._api(f"/api/documents/{doc}/state", {"target_id":event,"hidden":True})
        payload["filename"] = "renamed.txt"
        self.assertEqual(self._api("/api/documents", payload)["doc_id"], doc)
        dto = self._api(f"/api/documents/{doc}/timeline")
        self.assertEqual(dto["notes"], notes)
        self.assertEqual(dto["item_state"][event], {"reviewed":True,"hidden":True})

    def test_quality_endpoint_and_doc_quality(self):
        import backend.server as S
        import json as _json
        import os as _os
        fx = _os.path.join(BASE, "eval", "latest.json")
        self.assertTrue(_os.path.isfile(fx), "run eval/metrics.py first")
        with open(fx) as fh:
            rep = _json.load(fh)
        for k in ("job_extraction", "gap", "cases"):
            self.assertIn(k, rep)
        with open(GOPAL, "rb") as fh:
            raw = fh.read()
        sub = self._api("/api/documents", {"filename": "g.pdf",
                                           "content_b64": base64.b64encode(raw).decode()})
        tl = self._api(f"/api/documents/{sub['doc_id']}/timeline")
        q = tl.get("quality", {})
        for k in ("dated_events", "total_events", "dated_share", "mean_event_confidence"):
            self.assertIn(k, q)
        self.assertGreaterEqual(q["dated_share"], 0.0)
        self.assertLessEqual(q["dated_share"], 1.0)


if __name__ == "__main__":
    unittest.main()
