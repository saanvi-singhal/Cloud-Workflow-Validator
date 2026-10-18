# One violation per documented rule, plus a non-literal value that must not fire.
provider "aws" {
  region     = "eu-west-1"
  access_key = "AKIAEXAMPLEEXAMPLE"
}

variable "db_password" {
  default = "hunter2"
}

variable "acl" {
  default = "private"
}

resource "aws_s3_bucket" "public" {
  bucket = "public-site"
  acl    = "public-read"
}

resource "aws_s3_bucket" "unknown" {
  bucket = "computed-acl"
  acl    = var.acl
}

resource "aws_security_group" "ssh" {
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_db_instance" "main" {
  engine              = "postgres"
  instance_class      = "db.t3.micro"
  password            = var.db_password
  publicly_accessible = true
}
