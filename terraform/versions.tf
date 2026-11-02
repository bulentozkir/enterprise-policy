terraform {
  required_version = ">= 1.7.0, < 2.0.0"

  backend "local" {}

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.12.0"
    }
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2.13.0"
    }
  }
}

provider "azurerm" {
  features {}

  tenant_id                       = var.tenant_id
  subscription_id                 = var.subscription_id
  resource_provider_registrations = "none"
}

provider "azapi" {
  tenant_id                  = var.tenant_id
  subscription_id            = var.subscription_id
  use_cli                    = true
  skip_provider_registration = true
}
