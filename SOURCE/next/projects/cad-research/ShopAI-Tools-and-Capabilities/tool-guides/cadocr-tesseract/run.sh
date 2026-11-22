#!/usr/bin/env bash
set -Eeuo pipefail
exec python3 "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)/shopai_tool_runner.py" run cadocr-tesseract "$@"
