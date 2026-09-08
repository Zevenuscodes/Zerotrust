# Infra-level signal: the ALB can't reach a healthy app instance.
resource "aws_cloudwatch_metric_alarm" "unhealthy_hosts" {
  alarm_name          = "${var.project_name}-unhealthy-hosts"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  statistic           = "Average"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
    TargetGroup  = var.target_group_arn_suffix
  }

  alarm_actions = [var.sns_topic_arn]
}

# App-level signal: the risk engine is terminating an unusual number of
# sessions -- the "centralized monitoring" piece of the abstract, backed by
# the custom metric the app emits in app/metrics.py.
resource "aws_cloudwatch_metric_alarm" "high_risk_terminations" {
  alarm_name          = "${var.project_name}-high-risk-terminations"
  namespace           = "ZeroTrustAuth"
  metric_name         = "RiskDecision"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    Decision = "terminate"
  }

  alarm_actions = [var.sns_topic_arn]
}
