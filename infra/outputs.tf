output "app_url" {
  value       = "https://${aws_cloudfront_distribution.main.domain_name}"
  description = "Open this in your browser"
}

output "ecr_backend_url" {
  value       = aws_ecr_repository.backend.repository_url
  description = "Push your backend image here"
}

output "ecr_frontend_url" {
  value       = aws_ecr_repository.frontend.repository_url
  description = "Push your frontend image here"
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.main.id
}
