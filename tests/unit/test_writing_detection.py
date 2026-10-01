"""Detector configuration and adapter contract checks."""

import pytest
from arw_writing import detection


def test_missing_watermark_parameters_and_invalid_threshold():
    missing = detection.detect(
        "alpha beta", {"detectors": [{"backend": "hmac_green"}]}
    )[0]
    assert missing["status"] == "not_run" and missing["score"] is None
    invalid = detection.detect(
        "alpha beta",
        {
            "detectors": [
                {
                    "backend": "hmac_green",
                    "key": "public",
                    "vocabulary": ["alpha", "beta"],
                    "gamma": 0.5,
                    "z_threshold": float("nan"),
                }
            ]
        },
    )[0]
    assert invalid["status"] == "error" and invalid["score"] is None


def test_registered_backend_version_change_disables_delta():
    versions = iter(("fixture-v1", "fixture-v2"))

    def adapter(text, config, allow_network):
        result = detection._result(
            "classification", "fixture-version", next(versions), {}, text
        )
        return {**result, "status": "available", "score": 0.25}

    detection.register_backend("fixture-version", adapter)
    pair = detection.compare(
        "alpha", "beta", {"detectors": [{"backend": "fixture-version"}]}
    )["pairs"][0]
    assert not pair["comparable"] and pair["delta"] is None


def test_registered_backend_rejects_invalid_score():
    def adapter(text, config, allow_network):
        result = detection._result("classification", "fixture-invalid", "v1", {}, text)
        return {**result, "status": "available", "score": float("nan")}

    detection.register_backend("fixture-invalid", adapter)
    with pytest.raises(ValueError, match="invalid envelope"):
        detection.detect("alpha", {"detectors": [{"backend": "fixture-invalid"}]})


@pytest.mark.parametrize("config", [[], {"detectors": [{}]}, {"detectors": [4]}])
def test_malformed_config_rejected(config):
    with pytest.raises((TypeError, ValueError)):
        detection.detect("alpha", config)
