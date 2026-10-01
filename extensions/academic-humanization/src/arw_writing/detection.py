"""Opt-in text detection. Scores are observations, never authorship verdicts."""

from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import math
import re
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path
from urllib import error, request
from urllib.parse import urlsplit

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex

from . import gpt2_preset

SCHEMA = "arw.writing-detection.v1"
MAX_TEXT_BYTES = 65536


def _valid_threshold(value):
    return value is None or (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _fingerprint(value):
    return sha256_hex(canonical_json_bytes(value))


def _result(kind, backend, version, params, text, *, status="not_run", reason=None):
    return {
        "kind": kind,
        "backend": backend,
        "version": version,
        "parameters": params,
        "config_sha256": _fingerprint(
            {"kind": kind, "backend": backend, "version": version, "parameters": params}
        ),
        "input_sha256": sha256_hex(text.encode("utf-8")),
        "status": status,
        "reason": reason,
        "score": None,
        "score_name": None,
        "score_meaning": None,
        "threshold": None,
        "threshold_source": None,
        "label": None,
    }


def _watermark(text, config):
    """Detect the exact bundled HMAC/whitespace green-list generator contract."""
    key = config.get("key")
    vocab = config.get("vocabulary")
    gamma = config.get("gamma", 0.5)
    minimum = config.get("min_tokens", 30)
    version = "arw.hmac-green-whitespace.v1"
    public = {
        "gamma": gamma,
        "min_tokens": minimum,
        "vocabulary_sha256": _fingerprint(vocab) if isinstance(vocab, list) else None,
        "key_id": config.get("key_id"),
        "tokenizer": "literal whitespace, case-sensitive",
        "seed": "HMAC-SHA256(key, previous UTF-8 token)",
    }
    out = _result("watermark", "hmac_green", version, public, text)
    if not _valid_threshold(config.get("z_threshold")):
        return {**out, "status": "error", "reason": "invalid threshold"}
    if not isinstance(key, str) or not key or not isinstance(vocab, list):
        return {
            **out,
            "status": "not_run",
            "reason": "key and exact generator vocabulary required",
        }
    if (
        not isinstance(gamma, (int, float))
        or isinstance(gamma, bool)
        or not 0 < gamma < 1
        or not isinstance(minimum, int)
        or isinstance(minimum, bool)
        or minimum < 1
        or len(vocab) < 2
        or any(
            not isinstance(v, str) or not v or any(c.isspace() for c in v)
            for v in vocab
        )
        or len(set(vocab)) != len(vocab)
        or not 0 < round(gamma * len(vocab)) < len(vocab)
    ):
        return {**out, "status": "error", "reason": "invalid watermark parameters"}
    pieces = text.split()
    if any(piece not in vocab for piece in pieces):
        return {
            **out,
            "status": "unsupported",
            "reason": "input contains tokens outside the exact generator vocabulary",
        }
    if len(pieces) < minimum + 1:
        return {
            **out,
            "status": "unsupported",
            "reason": "insufficient eligible token transitions",
        }
    green = 0
    for previous, current in pairwise(pieces):
        # Per-context Bernoulli assignment. Generator must use this exact rule.
        digest = hmac.digest(key.encode(), previous.encode(), "sha256")
        seed = int.from_bytes(digest[:8], "big")
        candidates = sorted(
            vocab,
            key=lambda token: hashlib.sha256(
                seed.to_bytes(8, "big") + token.encode()
            ).digest(),
        )
        green += current in candidates[: round(gamma * len(vocab))]
    n = len(pieces) - 1
    effective_gamma = round(gamma * len(vocab)) / len(vocab)
    z = (green - effective_gamma * n) / math.sqrt(
        n * effective_gamma * (1 - effective_gamma)
    )
    return {
        **out,
        "status": "available",
        "score": z,
        "score_name": "green_token_z",
        "score_meaning": "One-sided green-token excess z under an approximate independent null; not AI probability",
        "p_value_approx": math.erfc(z / math.sqrt(2)) / 2,
        "eligible_transitions": n,
        "green_transitions": green,
        "threshold": config.get("z_threshold"),
        "threshold_source": "user_config"
        if config.get("z_threshold") is not None
        else None,
        "limitations": "Only the exact bundled HMAC/whitespace generator; null independence and false-positive rate are uncalibrated for natural text.",
    }


def _model_digest(root):
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("model symlinks unsupported")
        if path.is_file():
            digest.update(str(path.relative_to(root)).encode())
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


def _naive_bayes_classifier(text, config):
    """Run a user supplied, fixed multinomial model entirely offline."""
    path = config.get("model_path")
    maximum = config.get("max_tokens", 1024)
    params = {
        "model_sha256": None,
        "target_label": config.get("label"),
        "max_tokens": maximum,
        "tokenizer": "lowercase ASCII words",
    }
    out = _result(
        "classification", "naive_bayes_local", "arw.multinomial-nb.v1", params, text
    )
    if not path:
        return {**out, "reason": "local model_path required"}
    try:
        if not isinstance(maximum, int) or maximum < 1 or maximum > 8192:
            raise ValueError("invalid max_tokens")
        if not _valid_threshold(config.get("threshold")):
            raise ValueError("invalid threshold")
        if Path(path).stat().st_size > 65536:
            raise ValueError("model exceeds 64 KiB")
        raw = Path(path).read_bytes()
        params["model_sha256"] = sha256_hex(raw)
        out = _result(
            "classification", "naive_bayes_local", "arw.multinomial-nb.v1", params, text
        )
        model = json.loads(raw)
        if not isinstance(model, dict):
            raise TypeError("model must be an object")
        if (
            model["schema_version"] != "arw.naive-bayes-model.v1"
            or model["tokenizer"] != "lowercase_ascii_words"
        ):
            raise ValueError("unsupported model schema or tokenizer")
        counts = model["class_token_counts"]
        if not isinstance(counts, dict) or len(counts) < 2:
            raise ValueError("at least two classes required")
        if any(
            not isinstance(name, str)
            or not isinstance(row, dict)
            or not row
            or any(
                not isinstance(token, str) or re.fullmatch(r"[a-z]+", token) is None
                for token in row
            )
            for name, row in counts.items()
        ):
            raise ValueError("invalid class names or token rows")
        vocab = set().union(*(set(row) for row in counts.values()))
        if not vocab or any(
            not isinstance(v, int) or isinstance(v, bool) or v < 0
            for row in counts.values()
            for v in row.values()
        ):
            raise ValueError("invalid token counts")
        label = config.get("label")
        if label not in counts:
            return {
                **out,
                "status": "unsupported",
                "reason": "target label absent from model",
            }
        if any(char.isalpha() and not char.isascii() for char in text):
            return {
                **out,
                "status": "unsupported",
                "reason": "non-ASCII alphabetic text outside tokenizer scope",
            }
        tokens = re.findall(r"[a-z]+", text.lower())
        if len(tokens) > maximum:
            return {
                **out,
                "status": "unsupported",
                "reason": "input exceeds configured model token limit",
            }
        if not tokens or not any(token in vocab for token in tokens):
            return {
                **out,
                "status": "unsupported",
                "reason": "no model vocabulary tokens in input",
            }
        scores = {}
        for name, row in counts.items():
            denominator = sum(row.values()) + len(vocab)
            scores[name] = sum(
                math.log((row.get(token, 0) + 1) / denominator)
                for token in tokens
                if token in vocab
            )
        peak = max(scores.values())
        normalizer = sum(math.exp(value - peak) for value in scores.values())
        score = math.exp(scores[label] - peak) / normalizer
        return {
            **out,
            "status": "available",
            "score": score,
            "score_name": "naive_bayes_normalized_likelihood",
            "label": label,
            "score_meaning": "Uncalibrated model likelihood normalized over supplied classes; not probability of AI authorship",
            "input_tokens": len(tokens),
            "threshold": config.get("threshold"),
            "threshold_source": "user_config"
            if config.get("threshold") is not None
            else None,
            "limitations": "Validity, languages, domain shift and false-positive rate depend on supplied training data; bundled synthetic fixture has no real-world validity.",
        }
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        ZeroDivisionError,
        OverflowError,
    ) as exc:
        return {**out, "status": "error", "reason": type(exc).__name__}


def _local_classifier(text, config, *, verified_model_digest=None):
    backend = "transformers_local"
    model_path = config.get("model_path")
    maximum = config.get("max_tokens", 512)
    params = {
        "model_sha256": None,
        "max_tokens": maximum,
        "label": config.get("label"),
        "language": config.get("language"),
        "device": "cpu",
    }
    out = _result(
        "classification", backend, "transformers-sequence-classification", params, text
    )
    if not model_path:
        return {**out, "reason": "local model_path required"}
    root = Path(model_path)
    if not root.is_dir():
        return {
            **out,
            "status": "unsupported",
            "reason": "local model directory unavailable",
        }
    try:
        torch = importlib.import_module("torch")
        transformers = importlib.import_module("transformers")

        if not isinstance(maximum, int) or maximum < 2 or maximum > 4096:
            raise ValueError("max_tokens must be 2..4096")
        if not _valid_threshold(config.get("threshold")):
            raise ValueError("invalid threshold")
        params["model_sha256"] = verified_model_digest or _model_digest(root)
        params["transformers_version"] = transformers.__version__
        params["torch_version"] = torch.__version__
        out = _result("classification", backend, transformers.__version__, params, text)
        tokenizer = transformers.AutoTokenizer.from_pretrained(
            root, local_files_only=True, trust_remote_code=False
        )
        model = transformers.AutoModelForSequenceClassification.from_pretrained(
            root, local_files_only=True, use_safetensors=True, trust_remote_code=False
        )
        batch = tokenizer(text, return_tensors="pt", truncation=False)
        input_count = int(batch["input_ids"].shape[-1])
        if input_count > maximum:
            return {
                **out,
                "status": "unsupported",
                "reason": "input exceeds configured model token limit",
                "input_tokens": input_count,
            }
        model.eval()
        with torch.no_grad():
            logits = model(**batch).logits[0]
            probabilities = torch.softmax(logits, dim=-1)
        label = config.get("label")
        labels = model.config.id2label
        index = next((i for i, name in labels.items() if name == label), None)
        if index is None:
            return {
                **out,
                "status": "unsupported",
                "reason": "configured target label absent from model",
            }
        return {
            **out,
            "status": "available",
            "score": float(probabilities[index]),
            "score_name": "model_softmax_target_label",
            "label": label,
            "score_meaning": "Uncalibrated model softmax for configured label; not probability of AI authorship",
            "input_tokens": input_count,
            "possibly_truncated": False,
            "threshold": config.get("threshold"),
            "threshold_source": "user_config"
            if config.get("threshold") is not None
            else None,
            "limitations": "Only for the supplied offline model's documented languages and length; false-positive rate is not measured here.",
        }
    except ImportError:
        return {
            **out,
            "status": "unsupported",
            "reason": "optional transformers and torch dependencies unavailable",
        }
    except (OSError, ValueError, RuntimeError) as exc:
        return {**out, "status": "error", "reason": type(exc).__name__}


def _openai_gpt2_detector(text, config):
    """Exact offline OpenAI GPT-2 output detector preset, English only."""
    backend = "openai_gpt2_detector_local"
    params = {
        "model_id": gpt2_preset.MODEL_ID,
        "revision": gpt2_preset.REVISION,
        "license": gpt2_preset.LICENSE,
        "model_file_sha256": dict(gpt2_preset.FILES),
        "label": "Fake",
        "language": "en",
        "max_tokens": 512,
    }
    out = _result("classification", backend, gpt2_preset.REVISION, params, text)
    model_path = config.get("model_path")
    if not model_path:
        return {**out, "reason": "explicit local model_path required"}
    root = Path(model_path)
    fault = gpt2_preset.verify_files(root)
    if fault:
        return {
            **out,
            "status": "unsupported" if "missing" in fault else "error",
            "reason": fault,
        }
    if any(char.isalpha() and not char.isascii() for char in text):
        return {
            **out,
            "status": "unsupported",
            "reason": "input outside conservative English character scope",
        }
    base = _local_classifier(
        text,
        {"model_path": str(root), "label": "Fake", "language": "en", "max_tokens": 512},
        verified_model_digest=_fingerprint(gpt2_preset.FILES),
    )
    params["transformers_version"] = base["parameters"].get("transformers_version")
    params["torch_version"] = base["parameters"].get("torch_version")
    out = _result("classification", backend, gpt2_preset.REVISION, params, text)
    return {
        **out,
        "status": base["status"],
        "reason": base["reason"],
        "score": base["score"],
        "score_name": base["score_name"],
        "score_meaning": "Uncalibrated softmax for the GPT-2 Fake class; not probability of authorship",
        "label": "Fake" if base["status"] == "available" else None,
        "input_tokens": base.get("input_tokens"),
        "limitations": "OpenAI's English GPT-2 output detector. No validated inference for ChatGPT, newer models, Chinese, or academic misconduct; false positives remain possible.",
    }


def _http_classifier(text, config, *, allow_network=False):
    endpoint = config.get("endpoint")
    try:
        parsed = urlsplit(endpoint) if isinstance(endpoint, str) else None
        public_endpoint = (
            f"{parsed.scheme}://{parsed.hostname}{(':' + str(parsed.port)) if parsed.port else ''}"
            if parsed and parsed.hostname
            else None
        )
    except ValueError:
        parsed = None
        public_endpoint = None
    valid_url = bool(
        parsed
        and parsed.scheme in ("https", "http")
        and parsed.netloc
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
        and (parsed.scheme != "http" or parsed.hostname in ("127.0.0.1", "localhost"))
    )
    params = {
        "endpoint": public_endpoint,
        "endpoint_path_sha256": sha256_hex(parsed.path.encode())
        if valid_url and parsed
        else None,
        "model": config.get("model"),
        "version": config.get("version"),
        "label": config.get("label"),
        "timeout_seconds": config.get("timeout_seconds", 10),
    }
    out = _result(
        "classification",
        "http_json",
        str(config.get("version", "unspecified")),
        params,
        text,
    )
    if not allow_network:
        return {**out, "reason": "external transmission requires --allow-network"}
    if not _valid_threshold(config.get("threshold")):
        return {**out, "status": "error", "reason": "invalid threshold"}
    if not valid_url:
        return {
            **out,
            "status": "error",
            "reason": "HTTPS endpoint required except loopback testing",
        }
    payload = json.dumps({"text": text, "model": config.get("model")}).encode()
    try:
        req = request.Request(
            endpoint, data=payload, headers={"Content-Type": "application/json"}
        )

        class NoRedirect(request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        with request.build_opener(request.ProxyHandler({}), NoRedirect).open(
            req, timeout=float(config.get("timeout_seconds", 10))
        ) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("response too large")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise TypeError("response must be an object")
        if not config.get("version") or data.get("version") != config["version"]:
            raise ValueError("provider version mismatch or absent")
        if config.get("label") is not None and data.get("label") != config["label"]:
            raise ValueError("provider label mismatch")
        score = data["score"]
        if (
            not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not math.isfinite(score)
            or not 0 <= score <= 1
        ):
            raise ValueError("invalid score")
        return {
            **out,
            "status": "available",
            "score": float(score),
            "score_name": "provider_score",
            "score_meaning": "Provider-supplied score; calibration and error rates unverified",
            "label": data.get("label"),
            "threshold": config.get("threshold"),
            "threshold_source": "user_config"
            if config.get("threshold") is not None
            else None,
        }
    except (error.URLError, TimeoutError, ValueError, KeyError, TypeError) as exc:
        return {**out, "status": "error", "reason": type(exc).__name__}


Backend = Callable[[str, dict, bool], dict]
BACKENDS: dict[str, Backend] = {}


def register_backend(name: str, backend: Backend):
    """Register an adapter; adapters return the same versioned result envelope."""
    if not name or name in BACKENDS:
        raise ValueError("duplicate or empty detector backend")
    BACKENDS[name] = backend


register_backend("hmac_green", lambda text, item, allow_network: _watermark(text, item))
register_backend(
    "naive_bayes_local",
    lambda text, item, allow_network: _naive_bayes_classifier(text, item),
)
register_backend(
    "transformers_local",
    lambda text, item, allow_network: _local_classifier(text, item),
)
register_backend(
    "openai_gpt2_detector_local",
    lambda text, item, allow_network: _openai_gpt2_detector(text, item),
)
register_backend(
    "http_json",
    lambda text, item, allow_network: _http_classifier(
        text, item, allow_network=allow_network
    ),
)


def detect(text, config, *, allow_network=False):
    if not isinstance(config, dict):
        raise TypeError("detector config must be a JSON object")
    if len(text.encode()) > MAX_TEXT_BYTES:
        raise ValueError("detection input exceeds 64 KiB")
    results = []
    for item in config.get("detectors", []):
        if not isinstance(item, dict):
            raise TypeError("detector must be an object")
        backend = item.get("backend")
        if backend not in BACKENDS:
            raise ValueError("unsupported detector backend")
        result = BACKENDS[backend](text, item, allow_network)
        if not isinstance(result, dict) or not isinstance(
            result.get("parameters"), dict
        ):
            raise TypeError("detector adapter returned invalid envelope")
        try:
            expected_fingerprint = _fingerprint(
                {
                    "kind": result.get("kind"),
                    "backend": result.get("backend"),
                    "version": result.get("version"),
                    "parameters": result["parameters"],
                }
            )
        except (TypeError, ValueError):
            raise ValueError("detector adapter returned invalid envelope") from None
        if (
            result.get("kind") not in ("classification", "watermark")
            or result.get("status")
            not in ("not_run", "unsupported", "error", "available")
            or result.get("backend") != backend
            or not isinstance(result.get("version"), str)
            or not result["version"]
            or result.get("input_sha256") != sha256_hex(text.encode())
            or result.get("config_sha256") != expected_fingerprint
            or (
                result["status"] == "available"
                and (
                    not isinstance(result.get("score_name"), str)
                    or not result["score_name"]
                    or not isinstance(result.get("score_meaning"), str)
                    or not result["score_meaning"]
                    or not isinstance(result.get("score"), (int, float))
                    or isinstance(result["score"], bool)
                    or not math.isfinite(result["score"])
                )
            )
            or (result["status"] != "available" and result.get("score") is not None)
        ):
            raise ValueError("detector adapter returned invalid envelope")
        results.append(result)
    return results


def compare(source, revision, config, *, allow_network=False):
    before, after = (
        detect(source, config, allow_network=allow_network),
        detect(revision, config, allow_network=allow_network),
    )
    pairs = []
    for a, b in zip(before, after):
        compatible = a["status"] == b["status"] == "available" and all(
            a[k] == b[k]
            for k in (
                "kind",
                "backend",
                "version",
                "parameters",
                "config_sha256",
                "score_name",
                "label",
            )
        )
        pairs.append(
            {
                "before": a,
                "after": b,
                "comparable": compatible,
                "delta": b["score"] - a["score"] if compatible else None,
                "delta_meaning": "after minus before in the detector's raw score units"
                if compatible
                else None,
            }
        )
    return {
        "schema_version": SCHEMA,
        "pairs": pairs,
        "interpretation": "Scores and deltas do not establish authorship, watermark absence, or evasion success.",
    }
