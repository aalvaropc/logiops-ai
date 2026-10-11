data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_availability_zones" "available" { state = "available" }
data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}
data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}
# Forwards Host (checked by the app in public mode) plus CloudFront-Viewer-Address,
# which the rate limiter uses to tell viewers apart behind shared edge servers.
data "aws_cloudfront_origin_request_policy" "all_viewer_and_cloudfront" {
  name = "Managed-AllViewerAndCloudFrontHeaders-2022-06"
}

locals {
  foundation_model_id = replace(var.bedrock_model_id, "global.", "")
  token_parameter_arn = "arn:${data.aws_partition.current.partition}:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.access_token_parameter_name}"
}

resource "aws_vpc" "demo" {
  cidr_block           = "10.72.0.0/16"
  enable_dns_hostnames = true
  tags                 = { Name = "logiops-ai-demo" }
}

resource "aws_internet_gateway" "demo" {
  vpc_id = aws_vpc.demo.id
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.demo.id
  cidr_block              = "10.72.1.0/24"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = false
  tags                    = { Name = "logiops-ai-public" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.demo.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.demo.id
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "app" {
  name_prefix = "logiops-ai-"
  description = "MCP origin reachable only from CloudFront"
  vpc_id      = aws_vpc.demo.id

  ingress {
    description     = "CloudFront origin HTTP"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    prefix_list_ids = [data.aws_ec2_managed_prefix_list.cloudfront.id]
  }

  egress {
    description = "AWS APIs and package installation"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_s3_bucket" "releases" {
  bucket_prefix = "logiops-ai-releases-"
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "releases" {
  bucket                  = aws_s3_bucket.releases.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "releases" {
  bucket = aws_s3_bucket.releases.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "releases" {
  bucket = aws_s3_bucket.releases.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_iam_role" "app" {
  name_prefix = "logiops-ai-ec2-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "app" {
  role = aws_iam_role.app.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["${aws_s3_bucket.releases.arn}/releases/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = [local.token_parameter_arn]
      },
      {
        Effect = "Allow"
        Action = ["ssm:GetParametersByPath"]
        Resource = [
          "arn:${data.aws_partition.current.partition}:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.config_parameter_path}",
          "arn:${data.aws_partition.current.partition}:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.config_parameter_path}/*"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["polly:SynthesizeSpeech"]
        Resource = ["*"]
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:CreateEvent",
          "bedrock-agentcore:ListEvents",
          "bedrock-agentcore:GetEvent",
          "bedrock-agentcore:DeleteEvent",
          "bedrock-agentcore:ListSessions",
          "bedrock-agentcore:RetrieveMemoryRecords",
          "bedrock-agentcore:ListMemoryRecords",
          "bedrock-agentcore:BatchDeleteMemoryRecords"
        ]
        Resource = [aws_bedrockagentcore_memory.app.arn]
      },
      {
        Effect = "Allow"
        Action = ["bedrock:InvokeModel"]
        Resource = [
          "arn:${data.aws_partition.current.partition}:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:inference-profile/${var.bedrock_model_id}",
          "arn:${data.aws_partition.current.partition}:bedrock:${var.aws_region}::foundation-model/${local.foundation_model_id}",
          "arn:${data.aws_partition.current.partition}:bedrock:::foundation-model/${local.foundation_model_id}"
        ]
      }
    ]
  })
}

resource "aws_iam_instance_profile" "app" {
  role = aws_iam_role.app.name
}

resource "aws_ebs_volume" "data" {
  availability_zone = aws_subnet.public.availability_zone
  type              = "gp3"
  size              = 8
  encrypted         = true
  tags              = { Name = "logiops-ai-sqlite" }

  lifecycle { prevent_destroy = true }
}

resource "aws_instance" "app" {
  ami                         = data.aws_ssm_parameter.al2023_ami.value
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public.id
  associate_public_ip_address = true
  vpc_security_group_ids      = [aws_security_group.app.id]
  iam_instance_profile        = aws_iam_instance_profile.app.name
  user_data = templatefile("${path.module}/bootstrap.sh.tftpl", {
    data_volume_id = aws_ebs_volume.data.id
    aws_region     = var.aws_region
    token_param    = var.access_token_parameter_name
    model_id       = var.bedrock_model_id
    config_path    = var.config_parameter_path
  })
  user_data_replace_on_change = false
  tags                        = { Name = "logiops-ai-demo" }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = 16
    encrypted             = true
    delete_on_termination = true
  }

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  credit_specification { cpu_credits = "standard" }

  # The AMI comes from a "latest" parameter; without this, every new Amazon Linux
  # release would make `plan` replace the instance. To roll out a new AMI or a
  # changed bootstrap template, run `terraform apply -replace=aws_instance.app`
  # and then scripts/deploy_ec2.py again (data survives on the EBS volume).
  lifecycle {
    ignore_changes = [ami, user_data]
  }

  depends_on = [aws_route_table_association.public, aws_iam_role_policy_attachment.ssm]
}

resource "aws_volume_attachment" "data" {
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.data.id
  instance_id = aws_instance.app.id
  # Stop SQLite cleanly before the volume is detached on replacement or destroy.
  stop_instance_before_detaching = true
}

# CloudFront's managed CachingDisabled policy cannot forward Authorization, so GET
# requests (incident reads from the UI and verify_remote.py) would reach the app
# without the bearer token. This policy forwards it; the app answers with
# Cache-Control: no-store, so nothing is actually cached.
resource "aws_cloudfront_cache_policy" "authorized_no_store" {
  name        = "logiops-ai-authorized-no-store"
  comment     = "Forward Authorization on every method; origin sends no-store"
  min_ttl     = 0
  default_ttl = 0
  max_ttl     = 1

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_brotli = false
    enable_accept_encoding_gzip   = false
    cookies_config { cookie_behavior = "none" }
    headers_config {
      header_behavior = "whitelist"
      headers { items = ["Authorization"] }
    }
    query_strings_config { query_string_behavior = "all" }
  }
}

resource "aws_eip" "app" {
  domain = "vpc"
}

resource "aws_eip_association" "app" {
  allocation_id = aws_eip.app.id
  instance_id   = aws_instance.app.id
  depends_on    = [aws_internet_gateway.demo]
}

resource "aws_cloudfront_distribution" "app" {
  enabled         = true
  is_ipv6_enabled = false
  comment         = "LogiOps AI Amazon hackathon demo"
  price_class     = "PriceClass_100"

  origin {
    domain_name = aws_eip.app.public_dns
    origin_id   = "logiops-ec2"

    custom_origin_config {
      http_port              = 8000
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
      # 60 s is the default quota; the agent enforces a 50 s deadline to fit inside it.
      origin_read_timeout = 60
    }
  }

  default_cache_behavior {
    target_origin_id         = "logiops-ec2"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = aws_cloudfront_cache_policy.authorized_no_store.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_and_cloudfront.id
    compress                 = false
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate { cloudfront_default_certificate = true }
  depends_on = [aws_eip_association.app]
}

# MCP Apps requires web hosts to render views through a sandbox proxy on a different
# origin. A second distribution gives the same origin a second hostname; the app only
# serves /mcp-app/sandbox.html under that hostname and answers 404 to everything else.
resource "aws_cloudfront_distribution" "sandbox" {
  enabled         = true
  is_ipv6_enabled = false
  comment         = "LogiOps AI MCP Apps sandbox origin"
  price_class     = "PriceClass_100"

  origin {
    domain_name = aws_eip.app.public_dns
    origin_id   = "logiops-ec2"

    custom_origin_config {
      http_port              = 8000
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
      # 60 s is the default quota; the agent enforces a 50 s deadline to fit inside it.
      origin_read_timeout = 60
    }
  }

  default_cache_behavior {
    target_origin_id         = "logiops-ec2"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = aws_cloudfront_cache_policy.authorized_no_store.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_and_cloudfront.id
    compress                 = false
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate { cloudfront_default_certificate = true }
  depends_on = [aws_eip_association.app]
}
