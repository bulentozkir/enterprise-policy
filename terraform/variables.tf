variable "tenant_id" {
  description = "Explicitly requested Entra tenant. Authentication is through the existing Azure CLI session."
  type        = string
  default     = "d24284e3-1ea5-4285-9b96-4d53f671284b"
}

variable "management_group_name" {
  description = "Definition location only. No policies or initiatives are assigned."
  type        = string
  default     = "contoso"

  validation {
    condition     = var.management_group_name == "contoso"
    error_message = "This package targets only the explicitly requested ContosoRoot management group."
  }
}

variable "subscription_id" {
  description = "Provider authentication context; all created definitions remain at the management-group scope."
  type        = string
  default     = "a0fdc749-441a-43a5-8297-29192ed42f79"
}

variable "acknowledge_coverage_gaps" {
  description = "Explicitly accept the documented Key Vault ARM-only coverage and certificate-expiry omission. Does not bypass missing-source checks."
  type        = bool
  default     = false
}

variable "expected_principal_object_id" {
  description = "Optional principal verified by deploy.ps1; prevents Terraform using a different cached Azure CLI identity."
  type        = string
  default     = ""
}
