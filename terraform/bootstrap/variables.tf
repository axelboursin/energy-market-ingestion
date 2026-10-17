variable "aws_region" {
  type    = string
  default = "eu-west-3"
}

variable "github_repository" {
  description = "owner/name allowed to deploy"
  type        = string
}
