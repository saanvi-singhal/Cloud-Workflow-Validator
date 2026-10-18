# The subnet refers to a misspelt VPC name.
resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
}

resource "aws_subnet" "app" {
  vpc_id     = aws_vpc.mian.id
  cidr_block = "10.0.1.0/24"
}
