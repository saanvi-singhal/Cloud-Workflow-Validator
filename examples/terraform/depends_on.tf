# Explicit depends_on next to inferred references.
resource "aws_s3_bucket" "artifacts" {
  bucket = "build-artifacts"
}

resource "aws_iam_role" "deployer" {
  name = "deployer"
}

resource "aws_instance" "builder" {
  ami           = "ami-12345678"
  instance_type = "t3.micro"
  iam_instance_profile = aws_iam_role.deployer.name

  depends_on = [
    aws_s3_bucket.artifacts,
    aws_iam_role.deployer,
  ]
}
