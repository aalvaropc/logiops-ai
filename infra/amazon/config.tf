locals {
  app_config = {
    LOGIOPS_COGNITO_ISSUER          = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.operators.id}"
    LOGIOPS_COGNITO_DOMAIN          = "https://${aws_cognito_user_pool_domain.operators.domain}.auth.${var.aws_region}.amazoncognito.com"
    LOGIOPS_COGNITO_CLIENT_ID       = aws_cognito_user_pool_client.demo_web.id
    LOGIOPS_MEMORY_ID               = aws_bedrockagentcore_memory.app.id
    LOGIOPS_DAILY_MODEL_CALLS       = tostring(var.daily_model_calls)
    LOGIOPS_DAILY_SPEECH_CHARS      = tostring(var.daily_speech_chars)
    LOGIOPS_GUEST_DAILY_MODEL_CALLS = tostring(var.guest_daily_model_calls)
  }
}

resource "aws_ssm_parameter" "config" {
  for_each = local.app_config
  name     = "${var.config_parameter_path}/${each.key}"
  type     = "String"
  value    = each.value
}
