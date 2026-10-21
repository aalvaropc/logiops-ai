output "sandbox_domain" {
  description = "Second hostname for the MCP Apps sandbox proxy (LOGIOPS_SANDBOX_HOST)"
  value       = aws_cloudfront_distribution.sandbox.domain_name
}

output "cloudfront_domain" {
  value = aws_cloudfront_distribution.app.domain_name
}

output "mcp_url" {
  value = "https://${aws_cloudfront_distribution.app.domain_name}/mcp"
}

output "instance_id" {
  value = aws_instance.app.id
}

output "release_bucket" {
  value = aws_s3_bucket.releases.bucket
}

output "access_token_parameter_name" {
  value = var.access_token_parameter_name
}

output "aws_region" {
  value = var.aws_region
}

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.operators.id
}

output "cognito_client_id" {
  value = aws_cognito_user_pool_client.demo_web.id
}

output "cognito_domain" {
  value = local.app_config.LOGIOPS_COGNITO_DOMAIN
}

output "memory_id" {
  value = aws_bedrockagentcore_memory.app.id
}

output "config_parameter_path" {
  value = var.config_parameter_path
}

output "spend_stop_policy_arn" {
  value = aws_iam_policy.spend_stop.arn
}

output "app_role_name" {
  value = aws_iam_role.app.name
}
