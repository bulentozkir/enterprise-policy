import json
from pathlib import Path
import re
import unittest

from validate import validate_field_accessor, validate_policy_expression


ROOT = Path(__file__).resolve().parents[1]


def load_policy(group, name):
    return json.loads((ROOT / group / "policies" / f"{name}.json").read_text(encoding="utf-8"))["properties"]


def expression(value, fields, parameters, current):
    if not isinstance(value, str) or not value.startswith("["):
        return value
    match = re.fullmatch(r"\[bool\(parameters\('([^']+)'\)\)\]", value)
    if match:
        return {"true": True, "false": False}[parameters[match[1]]]
    for pattern, values in [
        (r"\[parameters\('([^']+)'\)\]", parameters),
        (r"\[current\('([^']+)'\)\]", current),
    ]:
        match = re.fullmatch(pattern, value)
        if match:
            return values[match[1]]
    match = re.fullmatch(r"\[length\(parameters\('([^']+)'\)\)\]", value)
    if match:
        return len(parameters[match[1]])
    match = re.fullmatch(
        r"\[if\(contains\(resourceGroup\(\).tags, current\('([^']+)'\)\), "
        r"resourceGroup\(\).tags\[current\('\1'\)\], ''\)\]", value,
    )
    if match:
        tags = fields.get("tags") or {}
        key = current[match[1]]
        return tags[key] if key in tags else ""
    raise AssertionError(f"Unsupported fixture expression: {value}")


def equal(actual, expected):
    if isinstance(actual, bool) and isinstance(expected, str):
        return str(actual).casefold() == expected.casefold()
    if isinstance(actual, str) and isinstance(expected, str):
        return actual.casefold() == expected.casefold()
    return actual == expected


def matches(condition, fields, parameters, current=None):
    current = current or {}
    for operator in ["allOf", "anyOf"]:
        if operator in condition:
            results = [matches(child, fields, parameters, current) for child in condition[operator]]
            return all(results) if operator == "allOf" else any(results)
    if "not" in condition:
        return not matches(condition["not"], fields, parameters, current)
    if "count" in condition:
        count = condition["count"]
        if "field" in count:
            items = fields.get(count["field"], [])
        else:
            items = expression(count["value"], fields, parameters, current)
        actual = 0
        for item in items:
            item_fields, item_current = dict(fields), dict(current)
            if "field" in count:
                item_fields[count["field"]] = item
            else:
                item_current[count["name"]] = item
            actual += int("where" not in count or matches(count["where"], item_fields, parameters, item_current))
    elif "field" in condition:
        validate_field_accessor(condition["field"])
        field = expression(condition["field"], fields, parameters, current)
        if field.startswith("tags["):
            actual = fields.get("tags", {}).get(field[5:-1])
        else:
            actual = fields.get(field)
    else:
        actual = expression(condition["value"], fields, parameters, current)
    for operator, operand in condition.items():
        if operator in {"field", "value", "count"}:
            continue
        expected = expression(operand, fields, parameters, current)
        if operator == "exists":
            return (actual is not None) == (str(expected).lower() == "true")
        if operator == "equals":
            return equal(actual, expected)
        if operator in {"notEquals", "notMatch"}:
            return not equal(actual, expected)
        if operator == "less":
            return (actual or "") < expected
        if operator == "greater":
            return actual > expected
        if operator == "greaterOrEquals":
            return actual >= expected
        if operator == "in":
            return any(equal(actual, item) for item in expected)
        if operator == "notIn":
            return not any(equal(actual, item) for item in expected)
        if operator == "containsKey":
            return expected in (actual or {})
        if operator == "notContains":
            return expected not in (actual or "")
        raise AssertionError(f"Unsupported fixture operator: {operator}")
    raise AssertionError(f"Missing comparison in fixture: {condition}")


class PolicyRegressionTests(unittest.TestCase):
    def test_public_ip_ddos_protection_does_not_require_a_plan(self):
        props = load_policy("Hub", "hub-h07-public-ip-ddos-protection-enabled")
        prefix = "Microsoft.Network/publicIPAddresses/ddosSettings."
        for mode, plan, expected in [
            ("Enabled", None, False),
            ("Enabled", "any-plan", False),
            ("Disabled", None, True),
            ("Disabled", "any-plan", True),
            ("VirtualNetworkInherited", None, True),
            ("VirtualNetworkInherited", "any-plan", True),
            (None, None, True),
            ("", None, True),
        ]:
            fields = {"type": "Microsoft.Network/publicIPAddresses"}
            if mode is not None:
                fields[prefix + "protectionMode"] = mode
            if plan is not None:
                fields[prefix + "ddosProtectionPlan.id"] = plan
            with self.subTest(mode=mode, plan=plan):
                self.assertEqual(matches(props["policyRule"]["if"], fields, {}), expected)
        self.assertFalse(matches(props["policyRule"]["if"], {
            "type": "Microsoft.Network/virtualNetworks",
        }, {}))

    def test_kubernetes_dropdown_values_remain_booleans(self):
        policies = [
            (path, json.loads(path.read_text(encoding="utf-8"))["properties"])
            for path in (ROOT / "LandingZone" / "policies").glob("*.json")
        ]
        checked = 0
        for path, props in policies:
            if props["mode"] != "Microsoft.Kubernetes.Data":
                continue
            details = props["policyRule"]["then"]["details"]
            for name in ["warn", "allowHostNetwork", "forcePrivilegeEscalationToBeFalse"]:
                if name not in props["parameters"]:
                    continue
                checked += 1
                value = details["warn"] if name == "warn" else details["values"][name]
                for selected, expected in [("true", True), ("false", False)]:
                    with self.subTest(policy=path.name, parameter=name, selected=selected):
                        self.assertIs(expression(value, {}, {name: selected}, {}), expected)
        self.assertEqual(checked, 7)

    def test_aks_local_authentication_must_be_disabled_not_just_entra_integrated(self):
        props = load_policy("LandingZone", "landingzone-l14-aks-local-authentication-disabled")
        for disabled in [None, False, True]:
            for aad in [None, {}, {"managed": True}, {"managed": False}]:
                fields = {"type": "Microsoft.ContainerService/managedClusters"}
                if disabled is not None:
                    fields["Microsoft.ContainerService/managedClusters/disableLocalAccounts"] = disabled
                if aad is not None:
                    fields["Microsoft.ContainerService/managedClusters/aadProfile"] = aad
                with self.subTest(disableLocalAccounts=disabled, aadProfile=aad):
                    self.assertEqual(
                        matches(props["policyRule"]["if"], fields, {"enabled": "true"}),
                        disabled is not True,
                    )
                    self.assertFalse(matches(props["policyRule"]["if"], fields, {"enabled": "false"}))
        self.assertFalse(matches(props["policyRule"]["if"], {
            "type": "Microsoft.Storage/storageAccounts",
        }, {"enabled": "true"}))

    def test_sql_database_hybrid_benefit_excludes_master_serverless_and_pooled_databases(self):
        props = load_policy("Global", "global-r30-sql-database-ahb")
        prefix = "Microsoft.Sql/servers/databases/"
        base = {
            "type": "Microsoft.Sql/servers/databases", "name": "appdb",
            prefix + "sku.name": "GP_Gen5_2", prefix + "sku.tier": "GeneralPurpose",
            prefix + "licenseType": "LicenseIncluded",
        }
        for label, changes, expected in [
            ("provisioned vCore database", {}, True),
            ("hybrid benefit enabled", {prefix + "licenseType": "BasePrice"}, False),
            ("master database", {"name": "master"}, False),
            ("serverless database", {prefix + "sku.name": "GP_S_Gen5_2"}, False),
            ("DTU tier", {prefix + "sku.tier": "Standard"}, False),
            ("elastic pool member", {prefix + "elasticPoolId": "/subscriptions/x/pool"}, False),
        ]:
            with self.subTest(label):
                self.assertEqual(
                    matches(props["policyRule"]["if"], {**base, **changes}, {"enabled": "true"}), expected,
                )
        self.assertFalse(matches(props["policyRule"]["if"], base, {"enabled": "false"}))

    def test_field_function_results_cannot_be_dereferenced(self):
        for value in ["[field('tags')]", "[resourceGroup().tags[current('tag')]]"]:
            validate_policy_expression(value)
        for value in ["[field('tags')[current('tag')]]", "[field('tags').owner]"]:
            with self.subTest(value=value), self.assertRaisesRegex(AssertionError, "cannot be dereferenced"):
                validate_policy_expression(value)

    def test_field_accessors_reject_functions_azure_does_not_support(self):
        for value in ["tags", "[concat('tags[', parameters('tagName'), ']')]"]:
            validate_field_accessor(value)
        for value in [
            "[concat('tags[', current('tagnullcount'), ']')]",
            "[concat('tags[', field('name'), ']')]",
        ]:
            with self.subTest(value=value), self.assertRaisesRegex(AssertionError, "field accessors"):
                validate_field_accessor(value)

    def test_missing_resource_group_tags_are_findings_not_expression_errors(self):
        props = load_policy("Global", "global-r05-r05-required-resource-group-tags")
        params = {"mandatoryTags": ["owner", "costcenter", "environment"]}
        for tags, expected in [
            (None, True),
            ({}, True),
            ({"owner": "ops"}, True),
            ({"owner": "", "costcenter": "123", "environment": "prod"}, True),
            ({"owner": "ops", "costcenter": "123", "environment": "prod"}, False),
        ]:
            with self.subTest(tags=tags):
                self.assertEqual(matches(props["policyRule"]["if"], {
                    "type": "Microsoft.Resources/subscriptions/resourceGroups", "tags": tags,
                }, params), expected)

    def test_storage_tls_accepts_stronger_versions_than_selected_floor(self):
        props = load_policy("Global", "global-r09-r09-storage-minimum-tls")
        for threshold, actual, expected in [
            ("TLS1_0", "TLS1_2", False), ("TLS1_1", "TLS1_2", False),
            ("TLS1_2", "TLS1_2", False), ("TLS1_2", "TLS1_1", True),
            ("TLS1_2", None, True),
        ]:
            with self.subTest(threshold=threshold, actual=actual):
                self.assertEqual(matches(props["policyRule"]["if"], {
                    "type": "Microsoft.Storage/storageAccounts",
                    "Microsoft.Storage/storageAccounts/minimumTlsVersion": actual,
                }, {"minimumTlsVersion": threshold}), expected)

    def test_point_to_site_requires_nonempty_aad_only_authentication(self):
        props = load_policy("Hub", "hub-h10-h10-entra-only-point-to-site-vpn-authentication")
        prefix = "Microsoft.Network/virtualNetworkGateways/vpnClientConfiguration."
        base = {
            "type": "Microsoft.Network/virtualNetworkGateways",
            prefix + "vpnClientAddressPool.addressPrefixes": ["10.1.0.0/24"],
        }
        for auth, expected in [
            ([], True), (["Certificate"], True), (["notAAD"], True),
            (["AAD", "Radius"], True), (["AAD"], False),
        ]:
            with self.subTest(auth=auth):
                fields = {**base, prefix + "vpnAuthenticationTypes[*]": auth}
                self.assertEqual(matches(props["policyRule"]["if"], fields, {"enabled": "true"}), expected)
                self.assertFalse(matches(props["policyRule"]["if"], fields, {"enabled": "false"}))
        self.assertTrue(matches(props["policyRule"]["if"], base, {"enabled": "true"}))
        self.assertFalse(matches(props["policyRule"]["if"], {
            "type": "Microsoft.Network/virtualNetworkGateways",
        }, {"enabled": "true"}))

    def test_public_aks_api_requires_nonempty_authorized_ranges(self):
        props = load_policy("LandingZone", "landingzone-l17-l17-authorized-ranges-on-public-aks-api")
        prefix = "Microsoft.ContainerService/managedClusters/apiServerAccessProfile."
        for ranges, private, expected in [
            (None, False, True), ([], False, True), (["10.1.0.0/24"], False, False),
            ([], True, False), (None, True, False),
        ]:
            fields = {
                "type": "Microsoft.ContainerService/managedClusters",
                prefix + "enablePrivateCluster": private,
            }
            if ranges is not None:
                fields[prefix + "authorizedIPRanges"] = ranges
                fields[prefix + "authorizedIPRanges[*]"] = ranges
            with self.subTest(ranges=ranges, private=private):
                self.assertEqual(matches(props["policyRule"]["if"], fields, {"enabled": "true"}), expected)

    def test_postgresql_public_access_does_not_pass_for_missing_network_fields(self):
        props = load_policy("LandingZone", "landingzone-l26-l26-private-only-postgresql-networking")
        prefix = "Microsoft.DBforPostgreSQL/flexibleServers/network."
        for public, subnet, dns, expected in [
            ("Enabled", None, None, True), ("Disabled", None, None, False),
            (None, None, None, True), (None, "subnet-id", "dns-id", False),
            ("Enabled", "subnet-id", "dns-id", True), ("Disabled", "subnet-id", "dns-id", False),
            (None, "", "", True),
        ]:
            fields = {"type": "Microsoft.DBforPostgreSQL/flexibleServers"}
            for name, value in [
                ("publicNetworkAccess", public), ("delegatedSubnetResourceId", subnet),
                ("privateDnsZoneArmResourceId", dns),
            ]:
                if value is not None:
                    fields[prefix + name] = value
            with self.subTest(public=public, subnet=subnet, dns=dns):
                self.assertEqual(matches(props["policyRule"]["if"], fields, {"enabled": "true"}), expected)

    def test_sql_retention_requires_a_present_nonzero_duration(self):
        props = load_policy("LandingZone", "landingzone-l45-l45-sql-long-term-retention-enabled")
        condition = props["policyRule"]["then"]["details"]["existenceCondition"]
        prefix = "Microsoft.Sql/servers/databases/backupLongTermRetentionPolicies/"
        for durations, expected in [
            ({}, False),
            ({"weeklyRetention": "PT0S", "monthlyRetention": "PT0S", "yearlyRetention": "PT0S"}, False),
            ({"weeklyRetention": ""}, False),
            ({"weeklyRetention": "P0W"}, False),
            ({"weeklyRetention": "P1W"}, True),
            ({"yearlyRetention": "P1Y"}, True),
        ]:
            with self.subTest(durations=durations):
                self.assertEqual(matches(condition, {
                    prefix + name: value for name, value in durations.items()
                }, {}), expected)


if __name__ == "__main__":
    unittest.main()
