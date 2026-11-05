variables {
  tenant_id             = "00000000-0000-0000-0000-000000000001"
  subscription_id       = "00000000-0000-0000-0000-000000000002"
  management_group_name = "test-mg"
}

mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id       = "00000000-0000-0000-0000-000000000001"
      subscription_id = "00000000-0000-0000-0000-000000000002"
    }
  }
}

mock_provider "azapi" {}

run "custom_definitions_only" {
  command = plan

  variables {
    acknowledge_coverage_gaps = true
    existing_policy_imports   = {}
  }

  assert {
    condition     = length(azapi_resource.custom) == 74
    error_message = "Expected 74 Custom definitions after requested removals and retaining editable required-tag arrays."
  }
  assert {
    condition     = length(azapi_resource.initiative) == 3
    error_message = "Expected exactly Global, Hub and LandingZone initiatives."
  }
  assert {
    condition = alltrue([
      for definition in azapi_resource.custom :
      definition.body.properties.policyType == "Custom" &&
      definition.parent_id == "/providers/Microsoft.Management/managementGroups/test-mg"
    ])
    error_message = "Every definition must be Custom and scoped to the target management group."
  }
  assert {
    condition = alltrue([
      for definition in azapi_resource.custom :
      contains(["Audit", "AuditIfNotExists"], definition.body.properties.parameters.effect.defaultValue)
    ])
    error_message = "Every definition must default to an audit-family effect."
  }
  assert {
    condition     = length(azapi_resource.initiative["Global"].body.properties.policyDefinitions) == 22
    error_message = "Global must reference 22 implemented Custom definitions."
  }
  assert {
    condition     = length(azapi_resource.initiative["Hub"].body.properties.policyDefinitions) == 12
    error_message = "Hub must reference 12 implemented Custom definitions."
  }
  assert {
    condition     = length(azapi_resource.initiative["LandingZone"].body.properties.policyDefinitions) == 40
    error_message = "LandingZone must reference 40 implemented Custom definitions."
  }
  assert {
    condition     = local.simple_parameter_inputs
    error_message = "Inputs must be Portal pickers, fixed dropdowns or editable arrays with three defaults."
  }
  assert {
    condition = (
      length([
        for spec in local.parameter_specs : spec
        if try(jsonencode(spec.allowedValues) == jsonencode(["true", "false"]), false)
      ]) == 93 &&
      alltrue([
        for spec in local.parameter_specs :
        spec.type != "Boolean" &&
        (
          try(jsonencode(spec.allowedValues) == jsonencode(["true", "false"]), false) ?
          (spec.type == "String" && try(spec.defaultValue == "true", false)) : true
        )
      ])
    )
    error_message = "All 48 policy and 45 initiative true/false inputs must be String dropdowns defaulting to true."
  }
  assert {
    condition = alltrue([
      for row in ["H11", "H20"] :
      !contains(local.catalog.sets.Hub.covered_rows, row) &&
      contains(local.catalog.sets.Hub.excluded_rows, row) &&
      alltrue([for name in keys(local.policies) : !startswith(name, "hub-${lower(row)}-")]) &&
      alltrue([for name in keys(local.initiatives.Hub.properties.parameters) : !startswith(name, "${lower(row)}_")])
    ])
    error_message = "H11/H20 and all associated initiative parameters must be removed with explicit coverage gaps."
  }
  assert {
    condition = (
      !contains(local.catalog.sets.LandingZone.covered_rows, "L49") &&
      contains(local.catalog.sets.LandingZone.excluded_rows, "L49") &&
      alltrue([for name in keys(local.policies) : !startswith(name, "landingzone-l49-")]) &&
      alltrue([for name in keys(local.initiatives.LandingZone.properties.parameters) : !startswith(name, "l49_")])
    )
    error_message = "L49, including the remote-gateway and hub-selection inputs, must be removed."
  }
  assert {
    condition = (
      local.initiatives.LandingZone.properties.parameters.l14_effect.metadata.displayName == "L14 - Azure Kubernetes Service Clusters should not use Local Authentication" &&
      local.policies["landingzone-l14-aks-local-authentication-disabled"].properties.policyRule["if"].allOf[1].allOf[1].field == "Microsoft.ContainerService/managedClusters/disableLocalAccounts" &&
      local.policies["landingzone-l14-aks-local-authentication-disabled"].properties.policyRule["if"].allOf[1].allOf[1].notEquals == true
    )
    error_message = "L14 must use the requested label and audit clusters unless local authentication is disabled."
  }
  assert {
    condition = (
      toset(keys(local.policies["hub-h07-public-ip-ddos-protection-enabled"].properties.parameters)) == toset(["effect"]) &&
      local.policies["hub-h07-public-ip-ddos-protection-enabled"].properties.policyRule["if"].allOf[1].field == "Microsoft.Network/publicIPAddresses/ddosSettings.protectionMode" &&
      local.policies["hub-h07-public-ip-ddos-protection-enabled"].properties.policyRule["if"].allOf[1].notEquals == "Enabled" &&
      !can(local.initiatives.Hub.properties.parameters.h07_approvedPlanIds) &&
      !can(local.initiatives.Hub.properties.parameters.h07_acceptVirtualNetworkInherited)
    )
    error_message = "H07 must audit each Public IP's protection mode without requiring or approving a DDoS plan."
  }
  assert {
    condition = alltrue([
      for row in ["R18", "R20", "R21", "R23", "R24", "R25", "R31", "R32", "R33", "R34", "R35", "R36"] :
      !contains(local.catalog.sets.Global.covered_rows, row) &&
      contains(local.catalog.sets.Global.excluded_rows, row) &&
      alltrue([
        for name in keys(local.policies) : !startswith(name, "global-${lower(row)}-")
      ]) &&
      alltrue([
        for name in keys(local.initiatives.Global.properties.parameters) : !startswith(name, "${lower(row)}_")
      ])
    ])
    error_message = "Requested Global controls and all their variants/initiative parameters must be absent."
  }
  assert {
    condition = alltrue([
      for row in ["r04", "r05", "r06"] :
      local.initiatives.Global.properties.parameters["${row}_mandatoryTags"].type == "Array" &&
      jsonencode(local.initiatives.Global.properties.parameters["${row}_mandatoryTags"].defaultValue) == jsonencode(["owner", "costcenter", "environment"]) &&
      !can(local.initiatives.Global.properties.parameters["${row}_mandatoryTags"].allowedValues)
    ])
    error_message = "Required tags must remain editable arrays with three replaceable defaults."
  }
  assert {
    condition = (
      azapi_resource.initiative["Global"].body.properties.parameters.r26_enabled.type == "String" &&
      azapi_resource.initiative["Global"].body.properties.parameters.r26_enabled.defaultValue == "true" &&
      alltrue([
        for name, definition in azapi_resource.custom :
        toset(keys(definition.body.properties.parameters)) == toset(["effect", "enabled"])
        if startswith(name, "global-r26-")
      ])
    )
    error_message = "R26 must use a default-true dropdown for all matching VMs/VMSS in scope, not a resource-selection object."
  }
}

run "coverage_limit_requires_explicit_acknowledgment" {
  command = plan

  variables {
    acknowledge_coverage_gaps = false
    existing_policy_imports   = {}
  }

  expect_failures = [terraform_data.source_catalog]
}
