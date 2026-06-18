variable "aws_region" {
  default = "us-east-1"
}

variable "project_name" {
  default = "voice-agent"
}

variable "openai_api_key" {
  sensitive = true
}

variable "tavily_api_key" {
  sensitive = true
}

variable "db_password" {
  sensitive = true
}

variable "db_username" {
  default = "postgres"
}

variable "db_name" {
  default = "voice_agent_db"
}

# Set these after first ECR push
variable "backend_image" {
  description = "ECR image URI for backend"
  default     = "public.ecr.aws/nginx/nginx:latest"
}

variable "frontend_image" {
  description = "ECR image URI for frontend"
  default     = "public.ecr.aws/nginx/nginx:latest"
}
