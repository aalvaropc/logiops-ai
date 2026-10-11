locals {
  public_base     = "https://${aws_cloudfront_distribution.app.domain_name}"
  resource_server = "${local.public_base}/mcp"
  oauth_scopes    = ["openid", "email", "${local.resource_server}/incidents.operate", "${local.resource_server}/bookings.write"]
}

resource "aws_cognito_user_pool" "operators" {
  name                = "logiops-ai-operators"
  user_pool_tier      = "ESSENTIALS"
  mfa_configuration   = "OFF"
  deletion_protection = "INACTIVE"

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  password_policy {
    minimum_length                   = 14
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 3
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "admin_only"
      priority = 1
    }
  }
}

resource "aws_cognito_user_pool_domain" "operators" {
  domain                = "logiops-ai-${substr(sha256(data.aws_caller_identity.current.account_id), 0, 10)}"
  user_pool_id          = aws_cognito_user_pool.operators.id
  managed_login_version = 2
}

resource "aws_cognito_resource_server" "mcp" {
  identifier   = local.resource_server
  name         = "LogiOps AI MCP server"
  user_pool_id = aws_cognito_user_pool.operators.id

  scope {
    scope_name        = "incidents.operate"
    scope_description = "Approve, execute and change incident data"
  }

  scope {
    scope_name        = "bookings.write"
    scope_description = "Quote, book and pay carriers"
  }
}

resource "aws_cognito_user_pool_client" "demo_web" {
  name                                 = "demo-web"
  user_pool_id                         = aws_cognito_user_pool.operators.id
  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = local.oauth_scopes
  callback_urls                        = concat(["${local.public_base}/demo", "http://localhost:8000/demo"], var.extra_oauth_callback_urls)
  logout_urls                          = ["${local.public_base}/demo", "http://localhost:8000/demo"]
  supported_identity_providers         = ["COGNITO"]
  explicit_auth_flows                  = ["ALLOW_REFRESH_TOKEN_AUTH", "ALLOW_USER_SRP_AUTH"]
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  access_token_validity                = 60
  id_token_validity                    = 60
  refresh_token_validity               = 30

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  depends_on = [aws_cognito_resource_server.mcp]
}

resource "aws_cognito_managed_login_branding" "demo_web" {
  user_pool_id                = aws_cognito_user_pool.operators.id
  client_id                   = aws_cognito_user_pool_client.demo_web.id
  use_cognito_provided_values = true
}
