#!/bin/sh
# Docker entrypoint: read secrets and export as environment variables
for secret in /run/secrets/*; do
  [ -f "$secret" ] || continue
  var_name=$(basename "$secret" | tr '[:lower:]' '[:upper:]')
  export "$var_name"="$(cat "$secret")"
done
exec python bot.py