#!/bin/sh
set -eu

required_vars="APP_TENANT_ID APP_WEB_CLIENT_ID APP_API_SCOPE APP_API_BASE_URL APP_REDIRECT_URI"
missing=0

for key in $required_vars; do
    eval "value=\${$key:-}"
    if [ -z "$value" ]; then
        echo "Missing required runtime setting: $key" >&2
        missing=1
    fi
done

if [ "$missing" -ne 0 ]; then
    exit 1
fi

env | grep '^APP_' | while IFS='=' read -r key value; do
    escaped_value=$(printf '%s' "$value" | sed -e 's/[|&\\]/\\&/g')
    echo "Configuring $key"
    find /usr/share/nginx/html -type f -exec sed -i "s|${key}|${escaped_value}|g" '{}' +
done

if grep -R 'APP_\(TENANT_ID\|WEB_CLIENT_ID\|API_SCOPE\|API_BASE_URL\|REDIRECT_URI\)' /usr/share/nginx/html >/dev/null 2>&1; then
    echo 'One or more runtime placeholders were not replaced.' >&2
    exit 1
fi

echo 'Runtime configuration complete.'
