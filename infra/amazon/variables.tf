variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "instance_type" {
  type    = string
  default = "t3.small"
}

variable "bedrock_model_id" {
  type    = string
  default = "global.anthropic.claude-sonnet-4-6"

  validation {
    condition     = startswith(var.bedrock_model_id, "global.")
    error_message = "This deployment expects a global Bedrock inference profile."
  }
}

variable "config_parameter_path" {
  type    = string
  default = "/logiops-ai/config"

  validation {
    condition     = can(regex("^/[a-z0-9/-]+[a-z0-9]$", var.config_parameter_path))
    error_message = "Use an absolute SSM path without a trailing slash."
  }
}

variable "daily_model_calls" {
  type    = number
  default = 150
}

variable "extra_oauth_callback_urls" {
  type    = list(string)
  default = ["http://localhost:6274/oauth/callback", "http://localhost:6274/oauth/callback/debug"]
}

variable "access_token_parameter_name" {
  type    = string
  default = "/logiops-ai/access-token"

  validation {
    condition     = startswith(var.access_token_parameter_name, "/")
    error_message = "Use an absolute SSM parameter name."
  }
}
