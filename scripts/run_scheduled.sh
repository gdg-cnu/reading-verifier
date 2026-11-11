#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
export MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
export MYSQL_USER="${MYSQL_USER:-root}"
export MYSQL_DATABASE="${MYSQL_DATABASE:-reading_verifier}"
export MYSQL_PASSWORD="$(/usr/bin/security find-generic-password -a "$MYSQL_USER" -s reading-verifier-mysql -w)"
exec .venv/bin/python -m collector.main
