#!/usr/bin/env bash
set -euo pipefail

ENV_FILE=".env"

if [ -f "$ENV_FILE" ]; then
    echo "$ENV_FILE already exists — leaving Z-Wave keys untouched."
    exit 0
fi

gen_key() {
    # 16 bytes -> 32 hex chars, cryptographically random
    openssl rand -hex 16 | tr '[:lower:]' '[:upper:]'
}

cat > "$ENV_FILE" <<EOF
ZWAVE_KEY_S0_LEGACY=$(gen_key)
ZWAVE_KEY_S2_UNAUTHENTICATED=$(gen_key)
ZWAVE_KEY_S2_AUTHENTICATED=$(gen_key)
ZWAVE_KEY_S2_ACCESSCONTROL=$(gen_key)
ZWAVE_KEY_LR_S2_AUTHENTICATED=$(gen_key)
ZWAVE_KEY_LR_S2_ACCESSCONTROL=$(gen_key)
EOF

echo "Generated new Z-Wave security keys in $ENV_FILE"
echo "IMPORTANT: back this file up — losing it means losing access to any S2-included devices."
