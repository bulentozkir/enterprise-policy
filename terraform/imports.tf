variable "existing_policy_imports" {
  description = "Explicit IDs of this package's existing policy definitions to adopt into Terraform state; empty for a new deployment."
  type        = map(string)
  default     = {}
}

import {
  for_each = var.existing_policy_imports
  to       = azapi_resource.custom[each.key]
  id       = "${each.value}?api-version=2026-07-01"
}
