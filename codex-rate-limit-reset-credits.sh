#!/bin/sh

curl -sS \
    -H "Authorization: Bearer $(jq -r '.tokens.access_token' ~/.codex/auth.json)" \
    https://chatgpt.com/backend-api/wham/rate-limit-reset-credits \
    | jq -r '"available_count=\(.available_count)\n" + (.credits[]?.expires_at // empty)'
