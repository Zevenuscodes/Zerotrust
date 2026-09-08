resource "random_id" "suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "models" {
  bucket = "${var.project_name}-risk-models-${random_id.suffix.hex}"
  tags   = { Name = "${var.project_name}-risk-models" }
}

resource "aws_s3_bucket_public_access_block" "models" {
  bucket                  = aws_s3_bucket.models.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "models" {
  bucket = aws_s3_bucket.models.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "models" {
  bucket = aws_s3_bucket.models.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Free gateway endpoint so the app instance can reach S3 over the AWS
# private network instead of the public internet, even though it also has
# an IGW route -- keeps model-artifact traffic off the public path.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = var.route_table_ids
  tags              = { Name = "${var.project_name}-s3-endpoint" }
}
