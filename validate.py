from collections import Counter
import base64
import hashlib
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).parent
EXPECTED = {"Global": 33, "Hub": 15, "LandingZone": 43}
PARAMETER = re.compile(r"parameters\('([^']+)'\)", re.I)
FORBIDDEN = {"deployment", "roleDefinitionIds", "operations", "deploymentScope"}
OS_RELEASE_SELECTOR = re.compile(
    r"(?i)(?:imageSku|imageOffer|imageVersion|osVersion|supportedImageCriteria|"
    r"scopeToSupportedImages|listOf(?:Windows|Linux)ImageIdToInclude)"
)


def walk(value, path=""):
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk(child, f"{path}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}/{index}")


def validate():
    totals = Counter()
    for set_name, count in EXPECTED.items():
        folder = ROOT / set_name
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        initiative = json.loads((folder / "initiative.json").read_text(encoding="utf-8"))
        members = initiative["properties"]["policyDefinitions"]
        covered = {p["rowKey"] for p in manifest["policies"]}
        gaps = {gap["rowKey"] for gap in manifest.get("coverageGaps", [])}
        assert not covered.intersection(gaps), set_name
        assert len(covered | gaps) == count, set_name
        assert len(initiative["properties"]["parameters"]) <= 400, set_name
        for parameter, spec in initiative["properties"]["parameters"].items():
            assert "schema" not in spec or spec["type"] == "Object", (
                set_name, parameter, "schema is supported only on Object parameters"
            )
        publishable = {p["name"] for p in manifest["policies"] if p["publishable"]}
        assert {m["policyDefinitionReferenceId"] for m in members} == publishable, set_name
        assert len(members) == len(publishable), set_name
        for entry in manifest["policies"]:
            path = folder / entry["file"]
            document = json.loads(path.read_text(encoding="utf-8"))
            props = document["properties"]
            assert props["policyType"] == "Custom", path
            assert len(props.get("parameters", {})) <= 20, path
            assert len(props["displayName"]) <= 128 and len(props["description"]) <= 512, path
            params = props.get("parameters", {})
            for parameter, spec in params.items():
                assert "schema" not in spec or spec["type"] == "Object", (
                    path, parameter, "schema is supported only on Object parameters"
                )
            metadata = props.get("metadata", {})
            assert str(metadata.get("deprecated", "")).lower() != "true", path
            assert str(metadata.get("retired", "")).lower() != "true", path
            assert not props["displayName"].lower().startswith(("[retired", "[deprecated")), path
            references = set()
            for pointer, value in walk({"policyRule": props["policyRule"], "parameters": params}):
                assert not OS_RELEASE_SELECTOR.search(pointer), (path, "OS/image selector", pointer)
                if isinstance(value, str) and value.startswith("["):
                    assert not OS_RELEASE_SELECTOR.search(value), (path, "OS/image selector", pointer)
                    assert "requestContext().apiVersion" not in value, (path, "Request API gate", pointer)
            for pointer, value in walk(props["policyRule"]):
                if isinstance(value, str):
                    assert not value.startswith("[["), (path, pointer)
                    for name in PARAMETER.findall(value):
                        assert name in params, (path, "undefined parameter", name)
                        references.add(name)
                    if value.startswith("https://") and re.search(r"/v\d+(?:[./])", value):
                        raise AssertionError((path, "Pinned implementation URL remains in rule", pointer))
                if isinstance(value, dict):
                    assert not (set(value) & FORBIDDEN), (path, pointer)
                    if isinstance(value.get("count"), dict) and "field" in value["count"]:
                        assert value["count"]["field"].endswith("[*]"), (path, "Non-array count field", pointer)
                    if props["mode"] == "Microsoft.Kubernetes.Data" and "field" in value:
                        field = value["field"]
                        assert field in {"type", "location", "tags"} or field.startswith("[concat('tags["), (
                            path, "Unsupported provider-mode field", field
                        )
                    for operator in ["like", "notLike"]:
                        operand = value.get(operator)
                        if isinstance(operand, str) and not operand.startswith("["):
                            assert operand.count("*") <= 1, (path, "Invalid multi-wildcard operand", pointer)
            assert set(params) == references, (path, "Unused policy parameters", set(params) - references)
            then = props["policyRule"]["then"]
            if props["mode"] == "Microsoft.Kubernetes.Data":
                template = then["details"]["templateInfo"]
                assert template["sourceType"] == "Base64Encoded", path
                assert set(template) == {"sourceType", "content"}, path
                content = base64.b64decode(template["content"], validate=True)
                assert b"kind: ConstraintTemplate" in content, path
                asset = folder / entry["templateAsset"]["file"]
                assert asset.read_bytes() == content, path
            match = PARAMETER.search(then["effect"])
            assert match, path
            effect = params[match.group(1)]
            assert effect["defaultValue"] in {"Audit", "AuditIfNotExists"}, path
            allowed = {value.lower() for value in effect["allowedValues"]}
            assert allowed <= {"audit", "auditifnotexists", "deny", "disabled"}, path
            if effect["defaultValue"] == "AuditIfNotExists":
                assert allowed <= {"auditifnotexists", "disabled"}, path
            if props["mode"] == "Microsoft.KeyVault.Data":
                assert not entry["publishable"] and "reference-only" in entry["file"], path
            if entry["publishable"]:
                member = next(m for m in members if m["policyDefinitionReferenceId"] == entry["name"])
                assert set(member["parameters"]) == set(params), path
                for param, value in member["parameters"].items():
                    target = PARAMETER.search(value["value"])
                    assert target and target.group(1) in initiative["properties"]["parameters"], path
            totals["sourceDefinitions"] += 1
            totals["publishableDefinitions" if entry["publishable"] else "referenceOnly"] += 1
        totals["catalogRows"] += count
        totals["explicitCoverageGaps"] += len(gaps)
    return dict(totals)


if __name__ == "__main__":
    try:
        print(json.dumps({"status": "success", **validate()}, indent=2))
    except (AssertionError, KeyError, ValueError, OSError) as error:
        print(f"VALIDATION FAILED: {error}", file=sys.stderr)
        sys.exit(1)
