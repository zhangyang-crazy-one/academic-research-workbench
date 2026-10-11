"""Additive harness contracts; original Phase 4 schema bytes stay unchanged."""

from arw.kernel.state.harness_models import HarnessConfiguration
from arw.kernel.state.orchestration_models import HostIdentityReceiptV2


def harness_schema_documents() -> dict[str, dict[str, object]]:
    return {
        name: {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://academic-research-workbench.local/schemas/v1/{name}",
            **model.model_json_schema(mode="validation"),
        }
        for name, model in (
            ("harness-config.schema.json", HarnessConfiguration),
            ("host-identity-receipt-v2.schema.json", HostIdentityReceiptV2),
        )
    }
