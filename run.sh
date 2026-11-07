#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ -f .env ]]; then
    exec uv run --locked --env-file .env valutatrade "$@"
fi

exec uv run --locked valutatrade "$@"
