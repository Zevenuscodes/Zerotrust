variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Short name used to prefix/tag every resource"
  type        = string
  default     = "zero-trust-auth"
}

variable "instance_type" {
  description = "EC2 instance type for the app (free-tier eligible)"
  type        = string
  default     = "t3.micro"
}

variable "asg_min_size" {
  type    = number
  default = 1
}

variable "asg_max_size" {
  type    = number
  default = 2
}

variable "asg_desired_capacity" {
  type    = number
  default = 1
}

variable "app_port" {
  type    = number
  default = 8000
}

variable "db_instance_class" {
  description = "RDS instance class (free-tier eligible)"
  type        = string
  default     = "db.t3.micro"
}

variable "db_allocated_storage" {
  type    = number
  default = 20
}

variable "db_username" {
  type    = string
  default = "ztauth"
}

variable "db_password" {
  description = "RDS master password. Leave empty to auto-generate and store in SSM Parameter Store."
  type        = string
  default     = ""
  sensitive   = true
}

variable "jwt_secret" {
  description = "Secret used to sign JWTs. Leave empty to auto-generate and store in SSM Parameter Store."
  type        = string
  default     = ""
  sensitive   = true
}

variable "alert_email" {
  description = "Email address to receive CloudWatch alarm notifications (SNS subscription)"
  type        = string
}

variable "app_image_tag" {
  description = "Tag of the app image in ECR to deploy (push it there first, see infra/README.md)"
  type        = string
  default     = "latest"
}
