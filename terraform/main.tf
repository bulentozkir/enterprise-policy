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
  parameter_specs = flatten(concat(
    [for policy in values(local.policies) : values(policy.properties.parameters)],
    [for initiative in values(local.initiatives) : values(initiative.properties.parameters)]
  ))
  simple_parameter_inputs = alltrue([
    for spec in local.parameter_specs :
    !can(spec.schema) && (
      (
        contains(["String", "Array"], spec.type) &&
        (
          contains(["location", "resourceTypes", "storageSkus", "vmSKUs", "existingResourceGroups"], try(spec.metadata.strongType, "")) ||
          can(regex("^[A-Za-z][A-Za-z0-9.]+(/[A-Za-z][A-Za-z0-9]*)+$", try(spec.metadata.strongType, "")))
        )
      ) ||
      (
        contains(["String", "Array", "Integer", "Float", "DateTime"], spec.type) &&
        length(try(spec.allowedValues, [])) > 0
      ) ||
      (
        spec.type == "Array" &&
        try(length(spec.defaultValue), 0) == 3 &&
        alltrue(try([
          for value in spec.defaultValue :
          value == tostring(value) && trimspace(tostring(value)) != ""
        ], [false]))
      )
    )
  ])
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
      error_message = "Review the coverage gaps documented in catalog.json and set acknowledge_coverage_gaps=true to accept them. Unsupported controls are not deployed."
    }
    precondition {
      condition     = toset(keys(local.policies)) == local.expected_definition_names
      error_message = "Policy files differ from catalog.json. Regenerate the reviewed source catalog before deployment."
    }
    precondition {
      condition     = local.simple_parameter_inputs
      error_message = "Policy and initiative parameters must be Portal pickers, fixed dropdowns or editable arrays with three default strings; true/false inputs must use String dropdowns, not Boolean text inputs."
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

resource "azapi_resource" "custom" {
  for_each = local.policies

  type      = "Microsoft.Authorization/policyDefinitions@2026-07-01"
  name      = each.key
  parent_id = local.management_group_id
  body      = { properties = each.value.properties }

  # ARM advertises this stable API; the provider's bundled type catalog may lag.
  schema_validation_enabled = false
  ignore_missing_property   = false
  response_export_values    = ["properties.policyType"]

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

resource "azapi_resource" "initiative" {
  for_each = local.set_names

  type      = "Microsoft.Authorization/policySetDefinitions@2026-07-01"
  name      = local.initiatives[each.key].name
  parent_id = local.management_group_id
  body = {
    properties = merge(local.initiatives[each.key].properties, {
      policyDefinitions = [
        for reference in local.initiatives[each.key].properties.policyDefinitions : {
          policyDefinitionReferenceId = reference.policyDefinitionReferenceId
          policyDefinitionId          = azapi_resource.custom[reference.policyDefinitionReferenceId].id
          parameters                  = reference.parameters
        }
      ]
    })
  }

  schema_validation_enabled = false
  ignore_missing_property   = false
  response_export_values    = ["properties.policyType"]

  depends_on = [terraform_data.source_catalog]

  lifecycle {
    prevent_destroy = true
  }
}
