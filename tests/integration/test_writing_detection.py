"""Run real local algorithms and CLI against public synthetic inputs."""

import hashlib
import hmac
import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from threading import Thread

from arw_writing import detection
from arw_writing.detection import compare, detect

from .test_writing import prepared, proposal

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "tests/fixtures/writing_detection/synthetic_nb.json"


def _green(previous, vocab, key, gamma):
    digest = hmac.digest(key.encode(), previous.encode(), "sha256")
    seed = int.from_bytes(digest[:8], "big")
    return sorted(
        vocab,
        key=lambda token: hashlib.sha256(
            seed.to_bytes(8, "big") + token.encode()
        ).digest(),
    )[: round(gamma * len(vocab))]


def _generated(vocab, key):
    tokens = [vocab[0]]
    for _ in range(80):
        tokens.append(_green(tokens[-1], vocab, key, 0.5)[0])
    return " ".join(tokens)


def test_real_local_backends_and_noncomparable_status(tmp_path):
    vocab = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
    config = {
        "detectors": [
            {
                "backend": "naive_bayes_local",
                "model_path": str(MODEL),
                "label": "synthetic_a",
                "max_tokens": 100,
            },
            {
                "backend": "hmac_green",
                "key": "PUBLIC_SYNTHETIC_DEMO_ONLY",
                "key_id": "public-demo-v1",
                "vocabulary": vocab,
                "gamma": 0.5,
                "min_tokens": 30,
            },
        ]
    }
    before = _generated(vocab, "PUBLIC_SYNTHETIC_DEMO_ONLY")
    after = before.replace("alpha", "beta")
    report = compare(before, after, config)
    classification, watermark = report["pairs"]
    assert classification["before"]["status"] == "available"
    assert classification["before"]["score"] != classification["after"]["score"]
    assert classification["comparable"] and classification["delta"] is not None
    assert watermark["before"]["status"] == "available"
    assert watermark["before"]["green_transitions"] == 80
    assert watermark["before"]["score"] > 0
    assert watermark["comparable"]
    assert "PUBLIC_SYNTHETIC_DEMO_ONLY" not in json.dumps(report)
    missing = compare(before, after, {"detectors": [{"backend": "hmac_green"}]})[
        "pairs"
    ][0]
    assert missing["before"]["status"] == "not_run"
    assert not missing["comparable"] and missing["delta"] is None
    too_short = detect("alpha beta", config)[1]
    assert too_short["status"] == "unsupported" and too_short["score"] is None
    assert detect("汉字 alpha", config)[0]["status"] == "unsupported"
    config["detectors"][1]["gamma"] = 0.01
    assert detect(before, config)[1]["status"] == "error"


def test_cli_audit_fact_lock_and_local_detection(tmp_path):
    source = tmp_path / "source.txt"
    revision = tmp_path / "revision.txt"
    source.write_text(r"alpha alpha: 5% \cite{lee}.")
    revision.write_text(r"beta beta: 6% \cite{kim}.")
    config = tmp_path / "detectors.json"
    config.write_text(
        json.dumps(
            {
                "detectors": [
                    {
                        "backend": "naive_bayes_local",
                        "model_path": str(MODEL),
                        "label": "synthetic_a",
                    }
                ]
            }
        )
    )
    env = {
        **os.environ,
        "PYTHONPATH": f"{ROOT / 'src'}:{ROOT / 'extensions/academic-humanization/src'}",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "arw.cli",
            "writing",
            "audit",
            "--source",
            str(source),
            "--revision",
            str(revision),
            "--detectors",
            str(config),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(result.stdout)
    assert report["detection"]["pairs"][0]["before"]["status"] == "available"
    assert report["fact_lock"]["mechanical_status"] == "failed"
    assert report["fact_lock"]["semantic_status"] == "human_review_required"
    assert {f["check"] for f in report["fact_lock"]["report"]["findings"]} >= {
        "F1",
        "F2",
        "F4",
    }
    config.write_text("[]")
    bad = subprocess.run(
        [
            sys.executable,
            "-m",
            "arw.cli",
            "writing",
            "audit",
            "--source",
            str(source),
            "--revision",
            str(revision),
            "--detectors",
            str(config),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert bad.returncode == 65
    assert json.loads(bad.stdout)["code"] == "writing_invalid"


def test_source_bound_prepare_retains_unavailable_detector_and_review(tmp_path):
    run_root, service = prepared(tmp_path)
    config = {
        "detectors": [
            {
                "backend": "http_json",
                "endpoint": "https://example.org/detect",
                "version": "v1",
            }
        ]
    }
    result = service.prepare("artifact.manuscript", proposal(), detector_config=config)
    assert result["source_binding"]["artifact_id"] == "artifact.manuscript"
    pair = result["detection"]["pairs"][0]
    assert pair["before"]["status"] == pair["after"]["status"] == "not_run"
    assert pair["delta"] is None
    assert result["fact_lock"]["semantic_status"] == "human_review_required"
    assert result["disposition"] == "human_review"
    assert run_root.is_dir()


def test_http_protocol_simulation(monkeypatch):
    class Response:
        def __init__(self, body):
            self.body = BytesIO(body)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            return self.body.read(size)

    class Opener:
        def open(self, req, timeout):
            assert req.full_url == "https://example.org/detect"
            assert json.loads(req.data)["text"] == "alpha"
            return Response(b'{"score":0.7,"label":"synthetic","version":"v1"}')

    monkeypatch.setattr(detection.request, "build_opener", lambda *handlers: Opener())
    config = {
        "detectors": [
            {
                "backend": "http_json",
                "endpoint": "https://example.org/detect",
                "version": "v1",
                "label": "synthetic",
            }
        ]
    }
    out = detect("alpha", config, allow_network=True)[0]
    assert out["status"] == "available" and out["score"] == 0.7
    config["detectors"][0]["label"] = "different"
    assert detect("alpha", config, allow_network=True)[0]["status"] == "error"
    config["detectors"][0]["endpoint"] = "https://[bad"
    assert detect("alpha", config, allow_network=True)[0]["status"] == "error"


def test_http_requires_opt_in_and_rejects_redirect_and_mismatch():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(302 if self.path == "/redirect" else 200)
            if self.path == "/redirect":
                self.send_header("Location", "https://example.com/collect")
            self.end_headers()
            if self.path != "/redirect":
                self.wfile.write(
                    b'{"score": 0.7, "label": "synthetic", "version": "wrong"}'
                )

        def log_message(self, *args):
            pass

    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    except PermissionError:
        import pytest

        pytest.skip("sandbox denies loopback sockets")
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = f"http://127.0.0.1:{server.server_port}"
        config = {
            "detectors": [
                {"backend": "http_json", "endpoint": endpoint, "version": "v1"}
            ]
        }
        assert detect("private input", config)[0]["status"] == "not_run"
        assert (
            detect("private input", config, allow_network=True)[0]["status"] == "error"
        )
        config["detectors"][0]["endpoint"] = endpoint + "/redirect"
        assert (
            detect("private input", config, allow_network=True)[0]["status"] == "error"
        )
        config["detectors"][0]["endpoint"] = (
            "https://user:secret@example.com/path?token=secret"
        )
        redacted = detect("private input", config, allow_network=True)[0]
        assert redacted["status"] == "error" and "secret" not in json.dumps(redacted)
    finally:
        server.shutdown()
        server.server_close()
