terraform {
  required_version = ">= 1.7.0, < 2.0.0"

  backend "local" {}

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.12.0"
    }
  }
}

provider "azurerm" {
  features {}

  tenant_id                       = var.tenant_id
  subscription_id                 = var.subscription_id
  resource_provider_registrations = "none"
}
