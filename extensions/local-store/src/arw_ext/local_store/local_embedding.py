"""Digest-pinned offline token-vector backend; no model downloads or execution."""

import hashlib
import json
import math
import re
from pathlib import Path

from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.ports.semantic import EmbeddingIdentity


class LocalTokenEmbedding:
    """Mean token vectors from a caller-supplied JSON model.

    This small backend is useful for bounded domain vocabularies and reproducible
    qualification fixtures. It is not a general language model. Unknown-only
    text fails explicitly instead of producing a misleading zero vector.
    """

    def __init__(self, path: Path, *, expected_digest: str):
        path = Path(path).absolute()
        raw = read_retained_bytes(path.parent, path.name, max_bytes=1_048_576)
        if hashlib.sha256(raw).hexdigest() != expected_digest:
            raise ValueError("embedding model content digest mismatch")
        data = json.loads(raw)
        if set(data) != {"format", "model_id", "version", "dimensions", "tokens"}:
            raise ValueError("invalid local embedding model fields")
        if data["format"] != "arw.token-vectors.v1":
            raise ValueError("unsupported embedding model format")
        dimensions = data["dimensions"]
        if type(dimensions) is not int or not 1 <= dimensions <= 2048:
            raise ValueError("invalid embedding dimensions")
        if not isinstance(data["tokens"], dict) or not 1 <= len(data["tokens"]) <= 4096:
            raise ValueError("invalid embedding vocabulary")
        for key in ("model_id", "version"):
            if not isinstance(data[key], str) or not 1 <= len(data[key]) <= 128:
                raise ValueError("invalid embedding identity")
        self._tokens = {}
        for token, vector in data["tokens"].items():
            if not token or len(token) > 128 or token != token.casefold():
                raise ValueError("model tokens must be bounded casefolded strings")
            if (
                not isinstance(vector, list)
                or len(vector) != dimensions
                or any(
                    type(x) not in {int, float} or not math.isfinite(x) or abs(x) > 1e10
                    for x in vector
                )
            ):
                raise ValueError("invalid model vector")
            self._tokens[token] = vector
        self._identity = EmbeddingIdentity(
            data["model_id"],
            data["version"],
            expected_digest,
            dimensions,
            "arw.local-token-mean.casefold-unicode-words.v1",
        )

    @property
    def identity(self):
        return self._identity

    def embed(self, texts):
        results = []
        for text in texts:
            if not isinstance(text, str) or len(text.encode("utf-8")) > 65_536:
                raise ValueError("embedding input is invalid or too large")
            tokens = re.findall(r"[^\W_]+", text.casefold(), re.UNICODE)
            vectors = [self._tokens[t] for t in tokens if t in self._tokens]
            if not vectors:
                raise ValueError("embedding vocabulary does not cover this text")
            mean = [
                sum(v[i] for v in vectors) / len(vectors)
                for i in range(self.identity.dimensions)
            ]
            norm = math.sqrt(sum(x * x for x in mean))
            if not norm:
                raise ValueError("embedding has zero norm")
            results.append([x / norm for x in mean])
        return results
