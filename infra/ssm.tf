resource "aws_ssm_parameter" "openai_api_key" {
  name  = "/${var.project_name}/OPENAI_API_KEY"
  type  = "SecureString"
  value = var.openai_api_key
}

resource "aws_ssm_parameter" "tavily_api_key" {
  name  = "/${var.project_name}/TAVILY_API_KEY"
  type  = "SecureString"
  value = var.tavily_api_key
}
