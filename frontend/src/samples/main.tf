resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
}

resource "aws_subnet" "app" {
  vpc_id = aws_vpc.main.id
  tags   = { vpc = aws_vpc.mian.id }
}
