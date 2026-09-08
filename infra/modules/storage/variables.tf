variable "project_name" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "route_table_ids" {
  description = "Route tables (public + private) to associate the free S3 gateway endpoint with"
  type        = list(string)
}
