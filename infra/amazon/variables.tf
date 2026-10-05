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

variable "access_token_parameter_name" {
  type    = string
  default = "/logiops-ai/access-token"

  validation {
    condition     = startswith(var.access_token_parameter_name, "/")
    error_message = "Use an absolute SSM parameter name."
  }
}
