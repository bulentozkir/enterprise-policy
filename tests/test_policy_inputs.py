import json
from pathlib import Path
import unittest

from policy_inputs import validate_parameter_spec, validate_parameter_value
from render import materialize
from validate import PARAMETER, validate, walk


ROOT = Path(__file__).resolve().parents[1]
SETS = {"Global": 22, "Hub": 12, "LandingZone": 40}
REMOVED_ROWS = {"Global": set(), "Hub": {"H17"}, "LandingZone": {"L10", "L11"}}
REQUESTED_REMOVALS = {
    "Global": {
        "R18", "R20", "R21", "R23", "R24", "R25", "R31", "R32", "R33", "R34", "R35", "R36",
    },
    "Hub": {"H11", "H20"},
    "LandingZone": {"L49"},
}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def selected_value(spec):
    if "allowedValues" in spec:
        value = spec["allowedValues"][0]
    else:
        picker = spec["metadata"]["strongType"]
        if picker == "location":
            value = "westeurope"
        elif picker == "resourceTypes":
            value = "Microsoft.KeyVault/vaults"
        elif picker == "existingResourceGroups":
            value = "NetworkWatcherRG"
        else:
            provider, *types = picker.split("/")
            segments = "/".join(f"{kind}/selected" for kind in types)
            value = f"/subscriptions/test/resourceGroups/policy-input-tests/providers/{provider}/{segments}"
    return [value] if spec["type"] == "Array" else value


def matches_license(condition, fields, enabled):
    if "allOf" in condition:
        return all(matches_license(item, fields, enabled) for item in condition["allOf"])
    actual = enabled == "true" if condition.get("value") == "[bool(parameters('enabled'))]" else fields.get(condition.get("field"))
    if "equals" in condition:
        return actual == condition["equals"]
    if "notEquals" in condition:
        return actual != condition["notEquals"]
    raise AssertionError(f"Unexpected licensing fixture condition: {condition}")


class ParameterContractTests(unittest.TestCase):
    def test_only_picker_dropdown_or_editable_array_specs_are_accepted(self):
        for spec in [
            {"type": "String", "metadata": {"strongType": "Microsoft.OperationalInsights/workspaces"}},
            {"type": "Array", "metadata": {"strongType": "location"}},
            {"type": "String", "allowedValues": ["Audit", "Disabled"]},
            {"type": "Integer", "allowedValues": [29, 179], "defaultValue": 179},
            {"type": "String", "allowedValues": ["true", "false"], "defaultValue": "true"},
            {"type": "Array", "defaultValue": ["owner", "costcenter", "environment"]},
        ]:
            with self.subTest(spec=spec):
                validate_parameter_spec("input", spec)

    def test_free_form_and_invalid_picker_specs_are_rejected(self):
        for spec in [
            {"type": "Object", "schema": {"type": "object"}},
            {"type": "String"},
            {"type": "Array", "defaultValue": []},
            {"type": "Array", "defaultValue": ["owner", "costcenter"]},
            {"type": "Array", "defaultValue": ["owner", "costcenter", ""]},
            {"type": "Array", "defaultValue": ["owner", "costcenter", 123]},
            {"type": "Integer", "defaultValue": 179},
            {"type": "String", "allowedValues": []},
            {"type": "String", "metadata": {"strongType": "tags"}},
            {"type": "Object", "metadata": {"strongType": "resourceTypes"}},
            {"type": "Boolean", "defaultValue": True},
            {"type": "Boolean", "allowedValues": [True, False], "defaultValue": True},
            {"type": "Boolean", "allowedValues": ["true", "false"]},
        ]:
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                validate_parameter_spec("input", spec)

    def test_true_false_dropdown_values_are_strings(self):
        spec = {"type": "String", "allowedValues": ["true", "false"], "defaultValue": "true"}
        for value in ["true", "false"]:
            validate_parameter_value("enabled", spec, value)
        for value in [True, False, 1, 0, None, "True", "False", "yes", ""]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_parameter_value("enabled", spec, value)

    def test_true_false_dropdowns_require_both_choices_and_true_default(self):
        for spec in [
            {"type": "String", "allowedValues": ["true", "false"]},
            {"type": "String", "allowedValues": ["true", "false"], "defaultValue": "false"},
            {"type": "String", "allowedValues": ["false", "true"], "defaultValue": "true"},
            {"type": "String", "allowedValues": ["true"], "defaultValue": "true"},
        ]:
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                validate_parameter_spec("enabled", spec)

    def test_integer_dropdown_does_not_accept_boolean_or_unlisted_threshold(self):
        spec = {"type": "Integer", "allowedValues": [29, 179]}
        validate_parameter_value("retention", spec, 179)
        for value in [True, 30, "179", 179.0]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_parameter_value("retention", spec, value)

    def test_picker_arrays_reject_empty_required_selections_and_non_strings(self):
        spec = {"type": "Array", "metadata": {"strongType": "Microsoft.Network/virtualNetworks"}}
        for value in [[], [123], [""], [False], [{}], "resource-id"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_parameter_value("networks", spec, value)
        optional = {**spec, "defaultValue": []}
        validate_parameter_value("networks", optional, [])

    def test_editable_arrays_accept_replacements_but_not_invalid_items(self):
        spec = {"type": "Array", "defaultValue": ["owner", "costcenter", "environment"]}
        validate_parameter_spec("mandatoryTags", spec)
        for value in [["business-unit"], ["application", "team", "cost-code", "tier"]]:
            validate_parameter_value("mandatoryTags", spec, value)
        for value in [[], [" "], [123], [True], [{}], "owner"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_parameter_value("mandatoryTags", spec, value)


class PackageTests(unittest.TestCase):
    def test_all_package_contracts(self):
        result = validate()
        self.assertEqual(result["sourceDefinitions"], 74)
        self.assertEqual(result["publishableDefinitions"], 74)
        self.assertEqual(result["catalogRows"], 91)
        self.assertEqual(result["explicitCoverageGaps"], 20)

    def test_removed_controls_are_explicit_gaps_and_not_members(self):
        for group, expected in SETS.items():
            manifest = read_json(ROOT / group / "manifest.json")
            initiative = read_json(ROOT / group / "initiative.json")
            self.assertEqual(len(manifest["policies"]), expected)
            self.assertEqual(len(initiative["properties"]["policyDefinitions"]), expected)
            removed = {
                gap["rowKey"] for gap in manifest["coverageGaps"]
                if gap.get("reasonCode") == "unsupported-simple-input"
            }
            self.assertEqual(removed, REMOVED_ROWS[group])
            self.assertFalse(removed.intersection(entry["rowKey"] for entry in manifest["policies"]))

    def test_requested_controls_and_all_variants_are_removed(self):
        for group, rows in REQUESTED_REMOVALS.items():
            manifest = read_json(ROOT / group / "manifest.json")
            removed = {
                gap["rowKey"]: gap for gap in manifest["coverageGaps"]
                if gap.get("reasonCode") == "user-requested-removal"
            }
            self.assertEqual(set(removed), rows)
            self.assertEqual(len(manifest["coverageGaps"]), len({gap["rowKey"] for gap in manifest["coverageGaps"]}))
            for row, gap in removed.items():
                self.assertEqual(len(gap["removedDefinitions"]), {"R25": 4, "R32": 3}.get(row, 1))
                for name in gap["removedDefinitions"]:
                    self.assertFalse((ROOT / group / "policies" / f"{name}.json").exists(), name)
            for path in (ROOT / group / "policies").glob("*.json"):
                self.assertNotIn(read_json(path)["properties"]["metadata"]["catalogRow"], rows)
            initiative = read_json(ROOT / group / "initiative.json")["properties"]
            template = read_json(ROOT / group / "initiative.template.json")
            names = list(initiative["parameters"])
            names.extend(
                member["policyDefinitionReferenceId"] for member in initiative["policyDefinitions"]
            )
            names.extend(resource["name"] for resource in template["resources"])
            names.extend(read_json(ROOT / group / "assignment.parameter-defaults.json")["parameters"])
            names.extend(item["parameter"] for item in read_json(ROOT / group / "required-inputs.json"))
            for row in rows:
                self.assertFalse(any(
                    name.startswith((f"{row.lower()}_", f"{group.lower()}-{row.lower()}-")) for name in names
                ), (group, row))

    def test_required_tag_arrays_have_three_replaceable_defaults(self):
        definitions = read_json(ROOT / "Global" / "initiative.json")["properties"]["parameters"]
        supplied = {
            name: {"value": selected_value(spec)}
            for name, spec in definitions.items() if "defaultValue" not in spec
        }
        for row in ["r04", "r05", "r06"]:
            key = f"{row}_mandatoryTags"
            spec = definitions[key]
            self.assertEqual(spec["type"], "Array")
            self.assertEqual(spec["defaultValue"], ["owner", "costcenter", "environment"])
            self.assertNotIn("allowedValues", spec)
            supplied[key] = {"value": ["application", "service-team"]}
        _, parameters = materialize("Global", "test-mg", supplied)
        for row in ["r04", "r05", "r06"]:
            self.assertEqual(parameters[f"{row}_mandatoryTags"]["value"], ["application", "service-team"])

    def test_renderer_accepts_only_new_required_input_contracts(self):
        for group in SETS:
            definitions = read_json(ROOT / group / "initiative.json")["properties"]["parameters"]
            supplied = {
                name: {"value": selected_value(spec)}
                for name, spec in definitions.items() if "defaultValue" not in spec
            }
            with self.subTest(group=group):
                initiative, parameters = materialize(group, "test-mg", supplied)
                self.assertEqual(set(parameters), set(definitions))
                self.assertTrue(all(
                    "/managementGroups/test-mg/" in member["policyDefinitionId"]
                    for member in initiative["properties"]["policyDefinitions"]
                ))
                for name, spec in definitions.items():
                    if spec.get("allowedValues") == ["true", "false"]:
                        self.assertEqual(parameters[name]["value"], "true")

    def test_renderer_preserves_explicit_false_for_every_dropdown(self):
        for group in SETS:
            definitions = read_json(ROOT / group / "initiative.json")["properties"]["parameters"]
            supplied = {
                name: {"value": selected_value(spec)}
                for name, spec in definitions.items() if "defaultValue" not in spec
            }
            dropdowns = {
                name for name, spec in definitions.items()
                if spec.get("allowedValues") == ["true", "false"]
            }
            supplied.update({name: {"value": "false"} for name in dropdowns})
            _, parameters = materialize(group, "test-mg", supplied)
            for name in dropdowns:
                self.assertEqual(parameters[name]["value"], "false")

    def test_renderer_rejects_removed_and_legacy_inputs(self):
        for group, name, value in [
            ("Global", "r26_profile", {"resourceIds": ["old-id"]}),
            ("Global", "r24_workspaceId", "old-workspace"),
            ("Global", "r25_actionGroupIds", ["old-action-group"]),
            ("Global", "r25_actionGroupIds_1ed4de2", ["old-action-group"]),
            ("Global", "r25_actionGroupIds_6730d27", ["old-action-group"]),
            ("Global", "r25_actionGroupIds_c3c3bc1", ["old-action-group"]),
            ("Global", "r33_effect", "AuditIfNotExists"),
            ("Global", "r33_enabled", "true"),
            ("Global", "r33_approvedDcrIds", ["old-dcr"]),
            ("Global", "r34_settingName", "WDATP"),
            ("Hub", "h20_effect", "Audit"),
            ("Hub", "h20_enabled", "true"),
            ("Hub", "h20_retentionInDays", 179),
            ("Hub", "h11_effect", "AuditIfNotExists"),
            ("Hub", "h11_resourceGroupName", "NetworkWatcherRG"),
            ("Hub", "h07_approvedPlanIds", ["old-plan"]),
            ("Hub", "h07_acceptVirtualNetworkInherited", "true"),
            ("LandingZone", "l49_effect", "AuditIfNotExists"),
            ("LandingZone", "l49_approvedHubVnetIds", ["old-hub"]),
            ("LandingZone", "l49_useRemoteGateways", "true"),
            ("LandingZone", "l49_enabled", "true"),
        ]:
            with self.subTest(parameter=name), self.assertRaisesRegex(ValueError, "Unknown initiative parameters"):
                materialize(group, "test-mg", {name: {"value": value}})

    def test_renderer_rejects_non_dropdown_r26_switches(self):
        for value in [True, False, 1, 0, "True", "False", "yes", ""]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                materialize("Global", "test-mg", {"r26_enabled": {"value": value}})

    def test_every_scope_switch_defaults_to_true_with_a_boolean_guard(self):
        for group in SETS:
            for path in (ROOT / group / "policies").glob("*.json"):
                props = read_json(path)["properties"]
                if "enabled" not in props["parameters"]:
                    continue
                with self.subTest(policy=path.name):
                    self.assertEqual(props["parameters"]["enabled"]["defaultValue"], "true")
                    self.assertEqual(
                        props["policyRule"]["if"]["allOf"][0],
                        {"value": "[bool(parameters('enabled'))]", "equals": True},
                    )
                    guard = props["policyRule"]["if"]["allOf"][0]
                    self.assertTrue(matches_license(guard, {}, "true"))
                    self.assertFalse(matches_license(guard, {}, "false"))
                    self.assertFalse({"profile", "evaluationScope", "clusterScope"}.intersection(props["parameters"]))

    def test_all_true_false_dropdowns_cast_rule_consumers_to_booleans(self):
        policy_count = initiative_count = 0
        for group in SETS:
            initiative = read_json(ROOT / group / "initiative.json")
            for name, spec in initiative["properties"]["parameters"].items():
                self.assertNotEqual(spec["type"], "Boolean", (group, name))
                if spec.get("allowedValues") == ["true", "false"]:
                    initiative_count += 1
                    self.assertEqual(spec["type"], "String")
                    self.assertEqual(spec["defaultValue"], "true")
            for path in (ROOT / group / "policies").glob("*.json"):
                props = read_json(path)["properties"]
                dropdowns = set()
                for name, spec in props["parameters"].items():
                    self.assertNotEqual(spec["type"], "Boolean", (path.name, name))
                    if spec.get("allowedValues") == ["true", "false"]:
                        policy_count += 1
                        dropdowns.add(name)
                        self.assertEqual(spec["type"], "String")
                        self.assertEqual(spec["defaultValue"], "true")
                for pointer, value in walk(props["policyRule"]):
                    if isinstance(value, str):
                        for name in dropdowns.intersection(PARAMETER.findall(value)):
                            self.assertEqual(value, f"[bool(parameters('{name}'))]", (path.name, pointer))
        self.assertEqual(policy_count, 48)
        self.assertEqual(initiative_count, 45)

    def test_global_required_inputs_no_longer_include_r33(self):
        definitions = read_json(ROOT / "Global" / "initiative.json")["properties"]["parameters"]
        required = read_json(ROOT / "Global" / "required-inputs.json")
        self.assertEqual({item["parameter"] for item in required}, {
            "r01_listOfAllowedLocations",
            "r02_listOfAllowedLocations",
            "r03_listOfResourceTypesNotAllowed",
        })
        supplied = {
            item["parameter"]: {"value": selected_value(definitions[item["parameter"]])}
            for item in required
        }
        initiative, parameters = materialize("Global", "test-mg", supplied)
        self.assertEqual(len(initiative["properties"]["policyDefinitions"]), 22)
        self.assertFalse(any(name.startswith("r33_") for name in parameters))

    def test_l14_label_and_rule_check_disabled_local_authentication(self):
        props = read_json(
            ROOT / "LandingZone" / "policies" / "landingzone-l14-aks-local-authentication-disabled.json"
        )["properties"]
        self.assertEqual(
            props["displayName"],
            "Azure Kubernetes Service Clusters should not use Local Authentication",
        )
        reference = read_json(
            ROOT / "LandingZone" / "policies" / "landingzone-l15-l15-disable-aks-local-accounts.json"
        )["properties"]
        self.assertEqual(props["policyRule"], reference["policyRule"])
        initiative = read_json(ROOT / "LandingZone" / "initiative.json")["properties"]
        self.assertEqual(
            initiative["parameters"]["l14_effect"]["metadata"]["displayName"],
            "L14 - Azure Kubernetes Service Clusters should not use Local Authentication",
        )

    def test_landing_zone_defaults_need_no_removed_l49_inputs(self):
        self.assertEqual(read_json(ROOT / "LandingZone" / "required-inputs.json"), [])
        initiative, parameters = materialize("LandingZone", "test-mg", {})
        self.assertEqual(len(initiative["properties"]["policyDefinitions"]), 40)
        self.assertFalse(any(name.startswith("l49_") for name in parameters))

    def test_r26_uses_one_dropdown_for_vms_and_scale_sets(self):
        initiative = read_json(ROOT / "Global" / "initiative.json")
        self.assertEqual(
            initiative["properties"]["parameters"]["r26_enabled"]["type"], "String"
        )
        members = [
            member for member in initiative["properties"]["policyDefinitions"]
            if member["policyDefinitionReferenceId"].startswith("global-r26-")
        ]
        self.assertEqual(len(members), 2)
        for member in members:
            self.assertEqual(member["parameters"]["enabled"], {"value": "[parameters('r26_enabled')]"})
            self.assertEqual(set(member["parameters"]), {"effect", "enabled"})

    def test_r26_true_audits_all_matching_windows_resources_false_skips(self):
        for suffix, resource_type, os_field, license_field in [
            (
                "vm", "Microsoft.Compute/virtualMachines",
                "Microsoft.Compute/virtualMachines/storageProfile.osDisk.osType",
                "Microsoft.Compute/virtualMachines/licenseType",
            ),
            (
                "vmss", "Microsoft.Compute/virtualMachineScaleSets",
                "Microsoft.Compute/virtualMachineScaleSets/virtualMachineProfile.storageProfile.osDisk.osType",
                "Microsoft.Compute/virtualMachineScaleSets/virtualMachineProfile.licenseType",
            ),
        ]:
            document = read_json(ROOT / "Global" / "policies" / f"global-r26-r26-{suffix}-approved-license.json")
            props = document["properties"]
            self.assertEqual(props["parameters"]["enabled"]["type"], "String")
            self.assertEqual(props["parameters"]["enabled"]["defaultValue"], "true")
            self.assertEqual(set(props["parameters"]), {"effect", "enabled"})
            rule = props["policyRule"]["if"]
            for resource_id in ["/subscriptions/one/resourceGroups/a/example", "/subscriptions/two/resourceGroups/b/example"]:
                fields = {
                    "id": resource_id, "type": resource_type, os_field: "Windows", license_field: "None"
                }
                with self.subTest(suffix=suffix, resource_id=resource_id):
                    self.assertTrue(matches_license(rule, fields, "true"))
                    self.assertFalse(matches_license(rule, fields, "false"))
                    compliant = {**fields, license_field: "Windows_Server"}
                    self.assertFalse(matches_license(rule, compliant, "true"))
                    linux = {**fields, os_field: "Linux"}
                    self.assertFalse(matches_license(rule, linux, "true"))
                    other_type = {**fields, "type": "Microsoft.Storage/storageAccounts"}
                    self.assertFalse(matches_license(rule, other_type, "true"))

    def test_kubernetes_defaults_remain_fixed_without_free_form_selectors(self):
        for path in (ROOT / "LandingZone" / "policies").glob("*.json"):
            props = read_json(path)["properties"]
            if props["mode"] != "Microsoft.Kubernetes.Data":
                continue
            with self.subTest(policy=path.name):
                details = props["policyRule"]["then"]["details"]
                self.assertEqual(details["excludedNamespaces"], [
                    "kube-system", "gatekeeper-system", "azure-arc", "azure-extensions-usage-system"
                ])
                self.assertEqual(details["namespaces"], [])
                self.assertEqual(details["labelSelector"], {})
                self.assertNotIn("clusterScope", props["parameters"])
                self.assertEqual(props["parameters"]["enabled"]["defaultValue"], "true")
                for name in ["excludedImages", "excludedContainers"]:
                    if name in details["values"]:
                        self.assertEqual(details["values"][name], [])
                if "allowHostNetwork" in props["parameters"]:
                    self.assertEqual(details["values"]["allowedHostPorts"], [])

    def test_h07_requires_no_plan_selection(self):
        props = read_json(
            ROOT / "Hub" / "policies" / "hub-h07-public-ip-ddos-protection-enabled.json"
        )["properties"]
        self.assertEqual(set(props["parameters"]), {"effect"})
        self.assertNotIn("ddosProtectionPlan", json.dumps(props["policyRule"]))
        self.assertFalse(any(
            item["row"] == "H07" for item in read_json(ROOT / "Hub" / "required-inputs.json")
        ))

    def test_definition_names_describe_current_behavior(self):
        for group, stale, current in [
            ("Hub", "hub-h07-public-ip-ddos-approved-plan", "hub-h07-public-ip-ddos-protection-enabled"),
            (
                "LandingZone", "landingzone-l14-l14-microsoft-entra-cluster-integration",
                "landingzone-l14-aks-local-authentication-disabled",
            ),
        ]:
            names = {path.stem for path in (ROOT / group / "policies").glob("*.json")}
            self.assertNotIn(stale, names)
            self.assertIn(current, names)
            initiative = read_json(ROOT / group / "initiative.json")["properties"]
            members = {member["policyDefinitionReferenceId"] for member in initiative["policyDefinitions"]}
            self.assertEqual(members & {stale, current}, {current})

    def test_policy_text_does_not_claim_to_deny_or_reference_removed_selection_lists(self):
        for group in SETS:
            for path in (ROOT / group / "policies").glob("*.json"):
                props = read_json(path)["properties"]
                with self.subTest(policy=path.name):
                    self.assertNotRegex(props["displayName"], r"^Deny\b|should be denied$")
                    self.assertNotRegex(props["description"], r"^This policy denies\b")
                    self.assertNotRegex(
                        props["displayName"] + " " + props["description"],
                        r"(?i)\bselected\b.*\bFirewall Polic|explicitly selected",
                    )

    def test_initiative_descriptions_match_the_current_input_contract(self):
        for group in SETS:
            initiative = read_json(ROOT / group / "initiative.json")["properties"]
            template = next(
                resource for resource in read_json(ROOT / group / "initiative.template.json")["resources"]
                if resource["type"] == "Microsoft.Authorization/policySetDefinitions"
            )["properties"]
            for description in [initiative["description"], template["description"]]:
                with self.subTest(group=group):
                    self.assertNotRegex(description, r"(?i)boolean|opt-in")
                    self.assertIn("default to true", description)

    def test_every_dropdown_has_a_default_selection(self):
        for group in SETS:
            specs = list(read_json(ROOT / group / "initiative.json")["properties"]["parameters"].items())
            for path in (ROOT / group / "policies").glob("*.json"):
                specs.extend(read_json(path)["properties"]["parameters"].items())
            for name, spec in specs:
                if "allowedValues" in spec:
                    with self.subTest(group=group, parameter=name):
                        self.assertIn("defaultValue", spec)

    def test_hub_assignment_needs_no_required_inputs(self):
        self.assertEqual(read_json(ROOT / "Hub" / "required-inputs.json"), [])
        _, parameters = materialize("Hub", "test-mg", {})
        self.assertEqual(parameters["h21_acceptedModes"]["value"], ["Alert", "Deny"])

    def test_resource_target_and_exception_selectors_are_not_exposed(self):
        forbidden = {
            "profile", "evaluationScope", "clusterScope", "resourceIds", "excludedResourceIds",
            "excludedNetworkInterfaceIds", "excludedVirtualMachineIds", "excludedArcMachineIds",
        }
        for group in SETS:
            for path in (ROOT / group / "policies").glob("*.json"):
                params = read_json(path)["properties"]["parameters"]
                self.assertFalse(forbidden.intersection(params), path.name)


if __name__ == "__main__":
    unittest.main()
