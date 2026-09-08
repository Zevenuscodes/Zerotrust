"""Best-effort CloudWatch custom metrics for risk decisions. A no-op locally
(no AWS credentials) so it never blocks the request path; becomes real
telemetry once deployed with an instance role that can call
cloudwatch:PutMetricData (see infra/modules/iam)."""

import logging

from app.config import settings

logger = logging.getLogger("zero_trust_auth.metrics")

_NAMESPACE = "ZeroTrustAuth"
_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    if settings.model_store != "s3":
        return None  # only wired up in the AWS deployment
    try:
        import boto3

        _client = boto3.client("cloudwatch", region_name=settings.model_store_s3_region)
    except Exception:
        logger.warning("CloudWatch client unavailable; skipping metric emission", exc_info=True)
        _client = False
    return _client or None


def emit_decision(decision: str) -> None:
    client = _get_client()
    if client is None:
        return
    try:
        client.put_metric_data(
            Namespace=_NAMESPACE,
            MetricData=[
                {
                    "MetricName": "RiskDecision",
                    "Dimensions": [{"Name": "Decision", "Value": decision}],
                    "Value": 1,
                    "Unit": "Count",
                }
            ],
        )
    except Exception:
        logger.warning("Failed to emit CloudWatch metric", exc_info=True)
