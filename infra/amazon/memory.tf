resource "aws_bedrockagentcore_memory" "app" {
  name                  = "logiops_ai_memory"
  description           = "LogiOps AI: what each operator said and decided, across sessions"
  event_expiry_duration = 30
}

resource "aws_bedrockagentcore_memory_strategy" "preferences" {
  memory_id           = aws_bedrockagentcore_memory.app.id
  name                = "operator_preferences"
  type                = "USER_PREFERENCE"
  namespace_templates = ["/users/{actorId}/preferences"]
}

resource "aws_bedrockagentcore_memory_strategy" "facts" {
  memory_id           = aws_bedrockagentcore_memory.app.id
  name                = "operator_facts"
  type                = "SEMANTIC"
  namespace_templates = ["/users/{actorId}/facts"]
}
