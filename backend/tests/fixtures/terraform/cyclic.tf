# Two security groups that reference each other: a dependency cycle.
resource "aws_security_group" "app" {
  name = "app"

  egress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.db.id]
  }
}

resource "aws_security_group" "db" {
  name = "db"

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }
}

resource "aws_s3_bucket" "logs" {
  bucket = "logs-${aws_s3_bucket.logs.id}"
}
