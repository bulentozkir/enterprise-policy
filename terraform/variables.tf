variable "tenant_id" {
  description = "Entra tenant that owns the target management group. Authentication is through the existing Azure CLI session."
  type        = string
}

variable "management_group_name" {
  description = "Name (ID, not display name) of the management group that holds the definitions and initiatives. No policies or initiatives are assigned."
  type        = string
}

variable "subscription_id" {
  description = "Any subscription in the tenant, used only for provider authentication; all created definitions remain at the management-group scope."
  type        = string
}

variable "acknowledge_coverage_gaps" {
  description = "Set to true to accept the coverage gaps documented in catalog.json (controls that cannot be audited with a custom policy). Does not bypass missing-source checks."
  type        = bool
  default     = false
}

variable "expected_principal_object_id" {
  description = "Optional principal verified by deploy.ps1; prevents Terraform using a different cached Azure CLI identity."
  type        = string
  default     = ""
}
