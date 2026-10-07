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
