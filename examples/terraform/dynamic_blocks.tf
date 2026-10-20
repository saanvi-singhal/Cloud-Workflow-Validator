# dynamic blocks are analysed with the iterator in scope: `rule.value` and
# `port.value` name the current element, not other resources, so they create
# no edges. `var.ingress_rules`, `var.ports` and `aws_vpc.main` are real
# dependencies of the security group.
variable "ingress_rules" {
  type = list(object({ cidr = string, description = string }))
}

variable "ports" {
  type = list(number)
}

resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
}

resource "aws_security_group" "web" {
  name   = "web"
  vpc_id = aws_vpc.main.id

  dynamic "ingress" {
    for_each = var.ingress_rules
    iterator = rule
    content {
      description = rule.value.description
      from_port   = 443
      to_port     = 443
      protocol    = "tcp"
      cidr_blocks = [rule.value.cidr, aws_vpc.main.cidr_block]
    }
  }

  dynamic "egress" {
    for_each = var.ports
    content {
      from_port   = egress.value
      to_port     = egress.value
      protocol    = "tcp"
      cidr_blocks = [aws_vpc.main.cidr_block]
    }
  }
}
