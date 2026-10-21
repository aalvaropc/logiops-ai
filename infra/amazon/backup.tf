resource "aws_s3_bucket" "backups" {
  bucket_prefix = "logiops-ai-backups-"
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "backups" {
  bucket                  = aws_s3_bucket.backups.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "backups" {
  bucket = aws_s3_bucket.backups.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_lifecycle_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    id     = "seven-day-recovery"
    status = "Enabled"
    filter { prefix = "snapshots/" }
    expiration { days = 7 }
    noncurrent_version_expiration { noncurrent_days = 7 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
  depends_on = [aws_s3_bucket_versioning.backups]
}

resource "aws_s3_bucket_policy" "backups" {
  bucket = aws_s3_bucket.backups.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.backups.arn, "${aws_s3_bucket.backups.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

resource "aws_iam_role_policy" "backups" {
  role = aws_iam_role.app.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:PutObject", "s3:GetObject"]
      Resource = ["${aws_s3_bucket.backups.arn}/snapshots/*"]
    }]
  })
}

locals {
  deployment_script = templatefile("${path.module}/deploy.sh.tftpl", {
    aws_region  = var.aws_region
    token_param = var.access_token_parameter_name
    model_id    = var.bedrock_model_id
    config_path = var.config_parameter_path
  })
  recovery_setup = templatefile("${path.module}/recovery.sh.tftpl", {
    aws_region        = var.aws_region
    backup_bucket     = aws_s3_bucket.backups.bucket
    backup_code       = file("${path.module}/../../scripts/sqlite_backup.py")
    deployment_script = local.deployment_script
  })
}

output "backup_bucket" {
  value = aws_s3_bucket.backups.bucket
}

output "recovery_setup" {
  value     = local.recovery_setup
  sensitive = true
}
