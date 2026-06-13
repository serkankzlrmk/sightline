#!/bin/bash
# ============================================================
# create-instance.sh — Auto-retry Oracle Cloud VM creation
#
# Keeps trying until the instance is created.
# Oracle Cloud frequently runs out of Always Free capacity,
# so this script retries every 30 seconds until a slot opens up.
#
# Prerequisites:
#   1. Install OCI CLI: brew install oci-cli
#   2. Configure: oci setup config
#      - You'll need: OCID, API key (from Oracle Console → Profile → API Keys)
#   3. Fill in the variables below
#
# Usage:
#   bash create-instance.sh
# ============================================================

set -euo pipefail

# ── FILL IN THESE VALUES ────────────────────────────────────────
# Get these from Oracle Console:
#   Compartment: Identity → Compartments → OCID
#   Subnet: Networking → VCN → Subnets → OCID
#   AD: Compute → Instances → Create Instance → see AD name (e.g., "XyZG:EU-FRANKFURT-1-AD-1")
#   Image OCID: https://docs.oracle.com/en-us/iaas/images/image/1c5468f0-5907-4f14-8e5a-2e8b0bda9dd0/
#              (Ubuntu 24.04 for your region)

COMPARTMENT_ID=""       # e.g., ocid1.compartment.oc1..aaaa...
SUBNET_ID=""            # e.g., ocid1.subnet.oc1.eu-frankfurt-1.aaaa...
AVAILABILITY_DOMAIN=""  # e.g., "XyZG:EU-FRANKFURT-1-AD-1"
IMAGE_ID=""             # e.g., ocid1.image.oc1.eu-frankfurt-1.aaaa...
SSH_KEY_FILE="$HOME/.ssh/id_rsa.pub"  # or path to your public SSH key
INSTANCE_NAME="sightline"
SHAPE="VM.Standard.E2.1.Micro"
RETRY_INTERVAL=30       # seconds between retries
# ────────────────────────────────────────────────────────────────

# Validate required values
for var_name in COMPARTMENT_ID SUBNET_ID AVAILABILITY_DOMAIN IMAGE_ID; do
    if [ -z "${!var_name}" ]; then
        echo "✗ $var_name is empty! Edit this script and fill in the values."
        echo ""
        echo "How to find them:"
        echo "  COMPARTMENT_ID:  Oracle Console → Identity → Compartments → OCID"
        echo "  SUBNET_ID:       Oracle Console → Networking → VCN → Subnets → OCID"
        echo "  AVAILABILITY_DOMAIN: Oracle Console → Compute → Create Instance → see AD"
        echo "  IMAGE_ID:        https://docs.oracle.com/en-us/iaas/images/ → Ubuntu 24.04 → your region"
        exit 1
    fi
done

if [ ! -f "$SSH_KEY_FILE" ]; then
    echo "✗ SSH key not found at $SSH_KEY_FILE"
    echo "  Generate one: ssh-keygen -t rsa -b 4096"
    exit 1
fi

SSH_KEY=$(cat "$SSH_KEY_FILE")

echo "============================================================"
echo "  Oracle Cloud — Auto-Retry Instance Creation"
echo "============================================================"
echo "  Shape:    $SHAPE"
echo "  Name:     $INSTANCE_NAME"
echo "  AD:       $AVAILABILITY_DOMAIN"
echo "  Interval: ${RETRY_INTERVAL}s"
echo "============================================================"
echo ""

ATTEMPT=0
while true; do
    ATTEMPT=$((ATTEMPT + 1))
    TIMESTAMP=$(date +%H:%M:%S)
    echo "[$TIMESTAMP] Attempt #$ATTEMPT..."

    RESULT=$(oci compute instance launch \
        --compartment-id "$COMPARTMENT_ID" \
        --availability-domain "$AVAILABILITY_DOMAIN" \
        --shape "$SHAPE" \
        --subnet-id "$SUBNET_ID" \
        --image-id "$IMAGE_ID" \
        --display-name "$INSTANCE_NAME" \
        --ssh-authorized-keys "$SSH_KEY_FILE" \
        --metadata "{\"ssh_authorized_keys\": \"$SSH_KEY\"}" \
        2>&1) || true

    if echo "$RESULT" | grep -q "id"; then
        INSTANCE_ID=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('data',{}).get('id',''))" 2>/dev/null || echo "")
        echo ""
        echo "✅✅✅ INSTANCE CREATED! ✅✅✅"
        echo "  Instance ID: $INSTANCE_ID"
        echo "  Name: $INSTANCE_NAME"
        echo ""
        echo "  Get public IP:"
        echo "  oci compute instance list-vnic-attachments --compartment-id $COMPARTMENT_ID --instance-id $INSTANCE_ID"
        echo ""
        echo "  Next: SSH into the VM and run setup.sh!"
        break
    fi

    if echo "$RESULT" | grep -qi "out of capacity"; then
        echo "  ⏳ Out of capacity — retrying in ${RETRY_INTERVAL}s..."
    else
        echo "  ⚠️ Error: $(echo "$RESULT" | head -3)"
        echo "  Retrying in ${RETRY_INTERVAL}s..."
    fi

    sleep "$RETRY_INTERVAL"
done