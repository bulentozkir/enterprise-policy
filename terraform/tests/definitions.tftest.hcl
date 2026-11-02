mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id       = "d24284e3-1ea5-4285-9b96-4d53f671284b"
      subscription_id = "a0fdc749-441a-43a5-8297-29192ed42f79"
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
    condition     = length(azapi_resource.custom) == 111
    error_message = "Expected all 111 implemented Custom definitions."
  }
  assert {
    condition     = length(azapi_resource.initiative) == 3
    error_message = "Expected exactly Global, Hub and LandingZone initiatives."
  }
  assert {
    condition = alltrue([
      for definition in azapi_resource.custom :
      definition.body.properties.policyType == "Custom" &&
      definition.parent_id == "/providers/Microsoft.Management/managementGroups/contoso"
    ])
    error_message = "Every definition must be Custom and scoped to ContosoRoot."
  }
  assert {
    condition = alltrue([
      for definition in azapi_resource.custom :
      contains(["Audit", "AuditIfNotExists"], definition.body.properties.parameters.effect.defaultValue)
    ])
    error_message = "Every definition must default to an audit-family effect."
  }
  assert {
    condition     = length(azapi_resource.initiative["Global"].body.properties.policyDefinitions) == 39
    error_message = "Global must reference 39 implemented Custom definitions."
  }
  assert {
    condition     = length(azapi_resource.initiative["Hub"].body.properties.policyDefinitions) == 16
    error_message = "Hub must reference 16 implemented Custom definitions."
  }
  assert {
    condition     = length(azapi_resource.initiative["LandingZone"].body.properties.policyDefinitions) == 56
    error_message = "LandingZone must reference 56 implemented Custom definitions."
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
