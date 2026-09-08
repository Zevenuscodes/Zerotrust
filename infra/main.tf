resource "random_password" "db" {
  length  = 20
  special = false
}

resource "random_password" "jwt" {
  length  = 40
  special = false
}

locals {
  db_password = var.db_password != "" ? var.db_password : random_password.db.result
  jwt_secret  = var.jwt_secret != "" ? var.jwt_secret : random_password.jwt.result

  jwt_secret_parameter_name  = "/${var.project_name}/jwt_secret"
  db_password_parameter_name = "/${var.project_name}/db_password"
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/${var.project_name}/app"
  retention_in_days = 14
}

resource "aws_sns_topic" "alerts" {
  name = "${var.project_name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_ssm_parameter" "jwt_secret" {
  name  = local.jwt_secret_parameter_name
  type  = "SecureString"
  value = local.jwt_secret
}

resource "aws_ssm_parameter" "db_password" {
  name  = local.db_password_parameter_name
  type  = "SecureString"
  value = local.db_password
}

module "network" {
  source = "./modules/network"

  project_name = var.project_name
  app_port     = var.app_port
}

module "storage" {
  source = "./modules/storage"

  project_name = var.project_name
  aws_region   = var.aws_region
  vpc_id       = module.network.vpc_id
  route_table_ids = [
    module.network.public_route_table_id,
    module.network.private_route_table_id,
  ]
}

module "iam" {
  source = "./modules/iam"

  project_name              = var.project_name
  s3_bucket_arn             = module.storage.bucket_arn
  jwt_secret_parameter_arn  = aws_ssm_parameter.jwt_secret.arn
  db_password_parameter_arn = aws_ssm_parameter.db_password.arn
  log_group_arn             = aws_cloudwatch_log_group.app.arn
}

module "database" {
  source = "./modules/database"

  project_name       = var.project_name
  private_subnet_ids = module.network.private_subnet_ids
  rds_sg_id          = module.network.rds_sg_id
  instance_class     = var.db_instance_class
  allocated_storage  = var.db_allocated_storage
  db_username        = var.db_username
  db_password        = local.db_password
}

module "compute" {
  source = "./modules/compute"

  project_name          = var.project_name
  aws_region            = var.aws_region
  vpc_id                = module.network.vpc_id
  public_subnet_ids     = module.network.public_subnet_ids
  alb_sg_id             = module.network.alb_sg_id
  app_sg_id             = module.network.app_sg_id
  instance_type         = var.instance_type
  asg_min_size          = var.asg_min_size
  asg_max_size          = var.asg_max_size
  asg_desired_capacity  = var.asg_desired_capacity
  app_port              = var.app_port
  app_image_tag         = var.app_image_tag
  instance_profile_name = module.iam.instance_profile_name

  jwt_secret_parameter_name  = local.jwt_secret_parameter_name
  db_password_parameter_name = local.db_password_parameter_name
  db_endpoint                = module.database.endpoint
  db_port                    = module.database.port
  db_username                = var.db_username
  s3_bucket_name             = module.storage.bucket_name
}

module "monitoring" {
  source = "./modules/monitoring"

  project_name            = var.project_name
  sns_topic_arn           = aws_sns_topic.alerts.arn
  alb_arn_suffix          = module.compute.alb_arn_suffix
  target_group_arn_suffix = module.compute.target_group_arn_suffix
}
