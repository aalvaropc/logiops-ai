resource "aws_route53_health_check" "demo" {
  fqdn              = aws_cloudfront_distribution.app.domain_name
  port              = 443
  type              = "HTTPS"
  resource_path     = "/healthz"
  request_interval  = 30
  failure_threshold = 3
  tags              = { Name = "logiops-ai-demo" }
}

resource "aws_sns_topic" "alerts" {
  name = "logiops-ai-alerts"
}

resource "aws_sns_topic_subscription" "alerts" {
  count     = var.spend_stop_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.spend_stop_email
}

resource "aws_cloudwatch_metric_alarm" "demo_down" {
  alarm_name          = "logiops-ai-demo-down"
  alarm_description   = "The deployed demo's /healthz has not answered through CloudFront for three minutes."
  namespace           = "AWS/Route53"
  metric_name         = "HealthCheckStatus"
  dimensions          = { HealthCheckId = aws_route53_health_check.demo.id }
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}
