output "alb_dns_name" {
  description = "Public URL of the app -- open this in a browser once deployed"
  value       = "http://${module.compute.alb_dns_name}"
}

output "ecr_repository_url" {
  description = "Push the built app image here before applying (see infra/README.md)"
  value       = module.compute.ecr_repository_url
}

output "db_endpoint" {
  value = module.database.endpoint
}

output "s3_model_bucket" {
  value = module.storage.bucket_name
}

output "asg_name" {
  value = module.compute.asg_name
}
