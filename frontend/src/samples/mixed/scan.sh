#!/usr/bin/env bash
set -euo pipefail
trivy fs --scanners vuln --severity HIGH,CRITICAL "${1:-/workspace}"
