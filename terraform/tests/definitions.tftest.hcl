mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id       = "d24284e3-1ea5-4285-9b96-4d53f671284b"
      subscription_id = "a0fdc749-441a-43a5-8297-29192ed42f79"
    }
  }
}

run "custom_definitions_only" {
  command = plan

  variables {
    acknowledge_coverage_gaps = true
  }

  assert {
    condition     = length(azurerm_policy_definition.custom) == 122
    error_message = "Expected all 122 implemented Custom definitions."
  }
  assert {
    condition     = length(azurerm_management_group_policy_set_definition.initiative) == 3
    error_message = "Expected exactly Global, Hub and LandingZone initiatives."
  }
  assert {
    condition = alltrue([
      for definition in azurerm_policy_definition.custom :
      definition.policy_type == "Custom" &&
      definition.management_group_id == "/providers/Microsoft.Management/managementGroups/contoso"
    ])
    error_message = "Every definition must be Custom and scoped to ContosoRoot."
  }
  assert {
    condition = alltrue([
      for definition in azurerm_policy_definition.custom :
      contains(["Audit", "AuditIfNotExists"], jsondecode(definition.parameters).effect.defaultValue)
    ])
    error_message = "Every definition must default to an audit-family effect."
  }
  assert {
    condition     = length(azurerm_management_group_policy_set_definition.initiative["Global"].policy_definition_reference) == 41
    error_message = "Global must reference 41 implemented Custom definitions."
  }
  assert {
    condition     = length(azurerm_management_group_policy_set_definition.initiative["Hub"].policy_definition_reference) == 25
    error_message = "Hub must reference 25 implemented Custom definitions."
  }
  assert {
    condition     = length(azurerm_management_group_policy_set_definition.initiative["LandingZone"].policy_definition_reference) == 56
    error_message = "LandingZone must reference 56 implemented Custom definitions."
  }
}

run "coverage_limit_requires_explicit_acknowledgment" {
  command = plan

  variables {
    acknowledge_coverage_gaps = false
  }

  expect_failures = [terraform_data.source_catalog]
}
