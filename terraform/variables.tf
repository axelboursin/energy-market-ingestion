variable "project" {
  type    = string
  default = "market-ingest"
}

variable "environment" {
  type    = string
  default = "prod"
}

variable "aws_region" {
  type    = string
  default = "eu-west-3"
}

variable "image_tag" {
  description = "Immutable image tag (git SHA) pushed to ECR by the deploy workflow."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{7,40}$", var.image_tag))
    error_message = "image_tag must be a git commit SHA, never a mutable tag such as latest."
  }
}

variable "ecr_repository_name" {
  description = "Repository created by terraform/bootstrap."
  type        = string
  default     = "market-ingest"
}

variable "bidding_zones" {
  description = "Bidding zones ingested on every run (Energy-Charts codes)."
  type        = list(string)
  default     = ["FR", "DE-LU", "BE", "NL", "ES"]
}

variable "alert_email" {
  type    = string
  default = "data-alerts@example.com"
}

variable "retention_days" {
  type    = number
  default = 3650
}
