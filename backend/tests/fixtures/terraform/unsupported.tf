# Constructs the v1 analyser reports instead of guessing.
locals {
  common_tags = { team = "platform" }
}

variable "subnet_ids" {
  type = list(string)
}

resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
  tags       = local.common_tags
}

resource "aws_network_interface" "nics" {
  for_each  = toset([for id in var.subnet_ids : id])
  subnet_id = each.value
}

resource "aws_instance" "web" {
  ami           = "ami-12345678"
  instance_type = "t3.micro"
  user_data     = <<EOT
#!/bin/sh
echo ${aws_vpc.main.id}
EOT
}
