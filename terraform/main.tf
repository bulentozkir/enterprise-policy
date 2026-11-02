locals {
  set_names           = toset(["Global", "Hub", "LandingZone"])
  management_group_id = "/providers/Microsoft.Management/managementGroups/${var.management_group_name}"
  catalog             = jsondecode(file("${path.module}/catalog.json"))

  policy_sources = flatten([
    for set_name in local.set_names : [
      for filename in fileset("${path.module}/../${set_name}/policies", "*.json") : {
        set      = set_name
        document = jsondecode(file("${path.module}/../${set_name}/policies/${filename}"))
      }
    ]
  ])
  policies = {
    for source in local.policy_sources : source.document.name => {
      set        = source.set
      properties = source.document.properties
    }
  }

  initiatives = {
    for set_name in local.set_names :
    set_name => jsondecode(file("${path.module}/../${set_name}/initiative.json"))
  }

  missing_rows = flatten([
    for set_name in local.set_names : [
      for row in local.catalog.sets[set_name].missing_rows : "${set_name}/${row}"
    ]
  ])
  coverage_gaps = flatten([
    for set_name in local.set_names : local.catalog.sets[set_name].coverage_gaps
  ])
  expected_definition_names = toset(flatten([
    for set_name in local.set_names : local.catalog.sets[set_name].publishable_definition_names
  ]))
}

data "azurerm_client_config" "current" {}

resource "terraform_data" "source_catalog" {
  input = local.catalog

  lifecycle {
    precondition {
      condition     = data.azurerm_client_config.current.tenant_id == var.tenant_id
      error_message = "Azure authentication resolved to a different Entra tenant."
    }
    precondition {
      condition     = var.expected_principal_object_id == "" || data.azurerm_client_config.current.object_id == var.expected_principal_object_id
      error_message = "Terraform authentication resolved to a different principal than the verified deployment preflight."
    }
    precondition {
      condition     = length(local.missing_rows) == 0
      error_message = "Deployment is blocked by missing custom-policy code: ${join(", ", local.missing_rows)}."
    }
    precondition {
      condition     = var.acknowledge_coverage_gaps || length(local.coverage_gaps) == 0
      error_message = "Review and explicitly accept documented Key Vault ARM-only coverage and the certificate-expiry omission. Unsupported clones are not deployed."
    }
    precondition {
      condition     = toset(keys(local.policies)) == local.expected_definition_names
      error_message = "Policy files differ from catalog.json. Regenerate the reviewed source catalog before deployment."
    }
    precondition {
      condition = alltrue([
        for set_name in local.set_names :
        length(local.catalog.sets[set_name].covered_rows) + length(local.catalog.sets[set_name].excluded_rows) == local.catalog.sets[set_name].expected_rows &&
        length(local.initiatives[set_name].properties.parameters) <= 400
      ])
      error_message = "The source catalog must cover every expected row and respect initiative parameter limits."
    }
  }
}

resource "azurerm_policy_definition" "custom" {
  for_each = local.policies

  name                = each.key
  management_group_id = local.management_group_id
  policy_type         = "Custom"
  mode                = each.value.properties.mode
  display_name        = each.value.properties.displayName
  description         = each.value.properties.description
  metadata            = jsonencode(try(each.value.properties.metadata, {}))
  parameters          = jsonencode(try(each.value.properties.parameters, {}))
  policy_rule         = jsonencode(each.value.properties.policyRule)

  depends_on = [terraform_data.source_catalog]

  lifecycle {
    prevent_destroy = true
    precondition {
      condition     = contains(["Audit", "AuditIfNotExists"], each.value.properties.parameters.effect.defaultValue)
      error_message = "Every custom definition must have an explicit audit-family default."
    }
    precondition {
      condition     = contains(["All", "Indexed", "Microsoft.Kubernetes.Data"], each.value.properties.mode)
      error_message = "An unsupported custom policy mode was included in the publishable folder."
    }
  }
}

resource "azurerm_management_group_policy_set_definition" "initiative" {
  for_each = local.set_names

  name                = local.initiatives[each.key].name
  management_group_id = local.management_group_id
  policy_type         = "Custom"
  display_name        = local.initiatives[each.key].properties.displayName
  description         = local.initiatives[each.key].properties.description
  metadata            = jsonencode(local.initiatives[each.key].properties.metadata)
  parameters          = jsonencode(local.initiatives[each.key].properties.parameters)

  dynamic "policy_definition_reference" {
    for_each = {
      for reference in local.initiatives[each.key].properties.policyDefinitions :
      reference.policyDefinitionReferenceId => reference
    }
    content {
      reference_id         = policy_definition_reference.key
      policy_definition_id = azurerm_policy_definition.custom[policy_definition_reference.key].id
      parameter_values     = jsonencode(policy_definition_reference.value.parameters)
    }
  }

  depends_on = [terraform_data.source_catalog]

  lifecycle {
    prevent_destroy = true
  }
}
