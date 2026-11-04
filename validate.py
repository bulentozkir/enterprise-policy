from collections import Counter
import base64
import hashlib
import json
from pathlib import Path
import re
import sys

from policy_inputs import validate_parameter_spec


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


def validate_field_accessor(value):
    assert isinstance(value, str), "Policy field accessor must be a string"
    if value.startswith("["):
        assert not re.search(r"\b(?:field|current)\s*\(", value, re.I), (
            "Policy field accessors cannot call field() or current(); use a value expression",
            value,
        )


def validate_policy_expression(value):
    assert not re.search(r"\bfield\('[^']+'\)\s*(?:\[|\.)", value, re.I), (
        "Policy field() results cannot be dereferenced; use a policy alias",
        value,
    )


def validate():
    totals = Counter()
    for set_name, count in EXPECTED.items():
        folder = ROOT / set_name
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        initiative = json.loads((folder / "initiative.json").read_text(encoding="utf-8"))
        members = initiative["properties"]["policyDefinitions"]
        entries = manifest["policies"]
        assert {path.stem for path in (folder / "policies").glob("*.json")} == {
            entry["name"] for entry in entries
        }, (set_name, "Policy files differ from manifest")
        assert manifest["customDefinitions"] == len(entries), set_name
        assert manifest["publishableDefinitions"] == len(members), set_name
        assert manifest["initiativeParameters"] == len(initiative["properties"]["parameters"]), set_name
        covered = {p["rowKey"] for p in manifest["policies"]}
        gaps = {gap["rowKey"] for gap in manifest.get("coverageGaps", [])}
        assert not covered.intersection(gaps), set_name
        assert len(covered | gaps) == count, set_name
        assert len(initiative["properties"]["parameters"]) <= 400, set_name
        for parameter, spec in initiative["properties"]["parameters"].items():
            validate_parameter_spec(f"{set_name}/{parameter}", spec)
        defaults = json.loads((folder / "assignment.parameter-defaults.json").read_text(encoding="utf-8"))
        assert defaults["parameters"] == {
            name: {"value": spec["defaultValue"]}
            for name, spec in initiative["properties"]["parameters"].items()
            if "defaultValue" in spec
        }, (set_name, "Assignment defaults differ from initiative")
        required = json.loads((folder / "required-inputs.json").read_text(encoding="utf-8"))
        assert {item["parameter"] for item in required} == {
            name for name, spec in initiative["properties"]["parameters"].items() if "defaultValue" not in spec
        }, (set_name, "Required inputs differ from initiative")
        arm_template = json.loads((folder / "initiative.template.json").read_text(encoding="utf-8"))
        template_policies = {
            resource["name"]: resource
            for resource in arm_template["resources"]
            if resource["type"] == "Microsoft.Authorization/policyDefinitions"
        }
        assert set(template_policies) == {entry["name"] for entry in entries}, set_name
        assert {path.relative_to(folder).as_posix() for path in (folder / "templates").glob("*.yaml")} == {
            entry["templateAsset"]["file"] for entry in entries if "templateAsset" in entry
        }, (set_name, "Kubernetes template files differ from manifest")
        referenced_inputs = set()
        publishable = {p["name"] for p in manifest["policies"] if p["publishable"]}
        assert {m["policyDefinitionReferenceId"] for m in members} == publishable, set_name
        assert len(members) == len(publishable), set_name
        for entry in manifest["policies"]:
            path = folder / entry["file"]
            document = json.loads(path.read_text(encoding="utf-8"))
            assert document["name"] == entry["name"], path
            assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["customDefinitionSha256"], (
                path, "Manifest digest differs from policy"
            )
            props = document["properties"]
            assert props["policyType"] == "Custom", path
            assert len(props.get("parameters", {})) <= 20, path
            assert len(props["displayName"]) <= 128 and len(props["description"]) <= 512, path
            params = props.get("parameters", {})
            for parameter, spec in params.items():
                validate_parameter_spec(f"{path.name}/{parameter}", spec)
            assert entry["requiredParameters"] == [
                name for name, spec in params.items() if "defaultValue" not in spec
            ], path
            template_props = template_policies[entry["name"]]["properties"]
            unescaped = unescape_arm(template_props)
            assert unescaped == {key: value for key, value in props.items() if key != "policyType"}, (
                path, "ARM template differs from standalone policy"
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
                    if value.startswith("["):
                        validate_policy_expression(value)
                    for name in PARAMETER.findall(value):
                        assert name in params, (path, "undefined parameter", name)
                        references.add(name)
                        if params[name].get("allowedValues") == ["true", "false"]:
                            assert value == f"[bool(parameters('{name}'))]", (
                                path, "True/false dropdown must be converted to a Boolean", pointer,
                            )
                    if value.startswith("https://") and re.search(r"/v\d+(?:[./])", value):
                        raise AssertionError((path, "Pinned implementation URL remains in rule", pointer))
                if isinstance(value, dict):
                    assert not (set(value) & FORBIDDEN), (path, pointer)
                    if "field" in value:
                        validate_field_accessor(value["field"])
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
                    referenced_inputs.add(target.group(1))
                    target_spec = initiative["properties"]["parameters"][target.group(1)]
                    for key in ["type", "allowedValues", "defaultValue"]:
                        assert params[param].get(key) == target_spec.get(key), (path, param, key)
                    assert params[param].get("metadata", {}).get("strongType") == target_spec.get(
                        "metadata", {}
                    ).get("strongType"), (path, param, "Picker metadata differs")
            totals["sourceDefinitions"] += 1
            totals["publishableDefinitions" if entry["publishable"] else "referenceOnly"] += 1
        assert referenced_inputs == set(initiative["properties"]["parameters"]), (
            set_name, "Unused initiative parameters"
        )
        template_sets = [
            resource for resource in arm_template["resources"]
            if resource["type"] == "Microsoft.Authorization/policySetDefinitions"
        ]
        assert len(template_sets) == 1 and template_sets[0]["name"] == initiative["name"], set_name
        expected_template = {key: value for key, value in initiative["properties"].items() if key != "policyType"}
        template_props = unescape_arm(template_sets[0]["properties"])
        for member in template_props["policyDefinitions"]:
            name = member["policyDefinitionReferenceId"]
            assert member["policyDefinitionId"] == (
                f"[extensionResourceId(managementGroup().id, 'Microsoft.Authorization/policyDefinitions', '{name}')]"
            ), (set_name, name)
            member["policyDefinitionId"] = next(
                item["policyDefinitionId"] for item in members if item["policyDefinitionReferenceId"] == name
            )
        assert template_props == expected_template, (set_name, "ARM initiative differs from standalone")
        assert set(template_sets[0]["dependsOn"]) == {
            f"[extensionResourceId(managementGroup().id, 'Microsoft.Authorization/policyDefinitions', '{name}')]"
            for name in publishable
        }, set_name
        catalog = json.loads((ROOT / "terraform" / "catalog.json").read_text(encoding="utf-8"))["sets"][set_name]
        assert set(catalog["publishable_definition_names"]) == publishable, set_name
        assert set(catalog["covered_rows"]) == covered, set_name
        assert set(catalog["excluded_rows"]) == gaps, set_name
        assert not catalog["missing_rows"], set_name
        totals["catalogRows"] += count
        totals["explicitCoverageGaps"] += len(gaps)
    return dict(totals)


def unescape_arm(value):
    if isinstance(value, dict):
        return {key: unescape_arm(child) for key, child in value.items()}
    if isinstance(value, list):
        return [unescape_arm(child) for child in value]
    if isinstance(value, str) and value.startswith("[["):
        return value[1:]
    return value


if __name__ == "__main__":
    try:
        print(json.dumps({"status": "success", **validate()}, indent=2))
    except (AssertionError, KeyError, ValueError, OSError) as error:
        print(f"VALIDATION FAILED: {error}", file=sys.stderr)
        sys.exit(1)
