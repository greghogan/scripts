#!/usr/bin/env bash

set -euo pipefail

AUTH_FILE="${CODEX_AUTH_FILE:-$HOME/.codex/auth.json}"
API_URL="${CODEX_RATE_LIMIT_URL:-https://chatgpt.com/backend-api/wham/rate-limit-reset-credits}"

usage() {
    cat <<EOF
Usage: $(basename "$0") [--json]

Fetch Codex rate-limit reset credits using the access token from:
  $AUTH_FILE

Options:
  --json   Print the full API response as JSON.
  -h       Show this help.
EOF
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "Error: required command not found: $1" >&2
        exit 1
    }
}

print_summary() {
    jq -r '
        "available_count=\(.available_count // 0)",
        (.credits[]?.expires_at // empty)
    '
}

JSON_OUTPUT=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --json)
            JSON_OUTPUT=true
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Error: unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
    shift
done

require_command curl
require_command jq

if [[ ! -f "$AUTH_FILE" ]]; then
    echo "Error: auth file not found: $AUTH_FILE" >&2
    exit 1
fi

ACCESS_TOKEN=$(jq -er '.tokens.access_token' "$AUTH_FILE") || {
    echo "Error: could not read .tokens.access_token from $AUTH_FILE" >&2
    exit 1
}

RESPONSE=$(
    curl --silent --show-error --fail-with-body \
        -H "Authorization: Bearer $ACCESS_TOKEN" \
        "$API_URL"
)

if [[ "$JSON_OUTPUT" == "true" ]]; then
    jq . <<<"$RESPONSE"
else
    print_summary <<<"$RESPONSE"
fi
