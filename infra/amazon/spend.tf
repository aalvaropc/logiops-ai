resource "aws_iam_policy" "spend_stop" {
  name_prefix = "logiops-ai-spend-stop-"
  description = "Cuts the demo instance off from Bedrock and Polly; the app then answers from its replay and the browser voice, and says so."
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Deny"
      Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "polly:SynthesizeSpeech"]
      Resource = "*"
    }]
  })
}

resource "aws_iam_role" "budget_action" {
  name_prefix = "logiops-ai-budget-action-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "budgets.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "budget_action" {
  role = aws_iam_role.budget_action.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = ["iam:AttachRolePolicy", "iam:DetachRolePolicy"]
      Resource  = aws_iam_role.app.arn
      Condition = { ArnEquals = { "iam:PolicyARN" = aws_iam_policy.spend_stop.arn } }
    }]
  })
}

resource "aws_budgets_budget" "spend_stop" {
  count        = var.spend_stop_email == "" ? 0 : 1
  name         = "logiops-ai-spend-stop"
  budget_type  = "COST"
  limit_amount = tostring(var.spend_stop_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_types {
    include_credit = false
    include_refund = false
  }
}

resource "aws_budgets_budget_action" "spend_stop" {
  count              = var.spend_stop_email == "" ? 0 : 1
  budget_name        = aws_budgets_budget.spend_stop[0].name
  action_type        = "APPLY_IAM_POLICY"
  approval_model     = "AUTOMATIC"
  notification_type  = "ACTUAL"
  execution_role_arn = aws_iam_role.budget_action.arn

  action_threshold {
    action_threshold_type  = "ABSOLUTE_VALUE"
    action_threshold_value = var.spend_stop_usd
  }

  definition {
    iam_action_definition {
      policy_arn = aws_iam_policy.spend_stop.arn
      roles      = [aws_iam_role.app.name]
    }
  }

  subscriber {
    address           = var.spend_stop_email
    subscription_type = "EMAIL"
  }
}
