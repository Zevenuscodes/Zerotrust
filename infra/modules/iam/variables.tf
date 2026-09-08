variable "project_name" {
  type = string
}

variable "s3_bucket_arn" {
  type = string
}

variable "jwt_secret_parameter_arn" {
  type = string
}

variable "db_password_parameter_arn" {
  type = string
}

variable "log_group_arn" {
  type = string
}
