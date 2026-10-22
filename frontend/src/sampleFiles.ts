import type { SourceFormat } from './types';
import terraformSample from './samples/main.tf?raw';
import dockerfileSample from './samples/Dockerfile?raw';
import yamlSample from './samples/ci.yml?raw';
import mixedWorkflow from './samples/mixed/ci.yml?raw';
import mixedDockerfile from './samples/mixed/Dockerfile?raw';
import mixedInstallScript from './samples/mixed/install-tools.sh?raw';
import mixedScanScript from './samples/mixed/scan.sh?raw';

// The same files are used to generate the mocks (frontend/scripts/generate_mocks.py).
export const SAMPLES: Record<Exclude<SourceFormat, 'mixed'>, string> = {
  terraform: terraformSample,
  dockerfile: dockerfileSample,
  yaml: yamlSample,
};

// A workflow, a Dockerfile and the scripts it uses, analysed together.
export const MIXED_SAMPLE: { name: string; content: string }[] = [
  { name: 'ci.yml', content: mixedWorkflow },
  { name: 'Dockerfile', content: mixedDockerfile },
  { name: 'install-tools.sh', content: mixedInstallScript },
  { name: 'scan.sh', content: mixedScanScript },
];

export const FILE_EXTENSION: Record<SourceFormat, string> = {
  terraform: '.tf',
  yaml: '.yml',
  dockerfile: '.dockerfile',
  mixed: '.txt',
};

export const MULTIFILE_TERRAFORM_SAMPLE: { name: string; content: string }[] = [
  {
    name: 'variables.tf',
    content: `variable "environment" {
  type    = string
  default = "production"
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "instance_type" {
  type    = string
  default = "t3.micro"
}

variable "unused_token" {
  type    = string
  default = "deprecated"
}
`,
  },
  {
    name: 'main.tf',
    content: `resource "aws_vpc" "main" {
  cidr_block = var.vpc_cidr

  tags = {
    Environment = var.environment
  }
}

resource "aws_subnet" "public" {
  vpc_id     = aws_vpc.main.id
  cidr_block = "10.0.1.0/24"

  tags = {
    Environment = var.environment
  }
}

resource "aws_instance" "web" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = var.instance_type
  subnet_id     = aws_subnet.public.id

  tags = {
    Environment = var.environment
  }
}
`,
  },
  {
    name: 'outputs.tf',
    content: `output "vpc_id" {
  value = aws_vpc.main.id
}

output "web_instance_id" {
  value = aws_instance.web.id
}
`,
  },
];
