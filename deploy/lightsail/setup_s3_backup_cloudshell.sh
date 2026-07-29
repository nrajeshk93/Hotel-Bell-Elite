#!/usr/bin/env bash
# Run this once in AWS CloudShell (same account as your Lightsail/S3 console).
# Creates a dedicated private backup bucket + IAM user for belleliteaccounts only.
# Does not modify Lightsail instances, networking, or website settings.

set -euo pipefail

REGION="${AWS_REGION:-ap-south-1}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="${BACKUP_BUCKET:-belleliteaccounts-db-backups-${ACCOUNT_ID}}"
IAM_USER="${BACKUP_IAM_USER:-belleliteaccounts-backup}"
POLICY_NAME="${BACKUP_POLICY_NAME:-BelleliteaccountsBackupS3Only}"
# Keep last 30 days only. S3 Standard is cheapest for 30-day retention
# (Glacier classes bill 90–180 day minimums even if you delete earlier).
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

echo "Account : $ACCOUNT_ID"
echo "Region  : $REGION"
echo "Bucket  : $BUCKET"
echo "IAM user: $IAM_USER"
echo "Retain  : ${RETENTION_DAYS} days"
echo

if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo "Bucket already exists: $BUCKET"
else
  aws s3api create-bucket \
    --bucket "$BUCKET" \
    --region "$REGION" \
    --create-bucket-configuration LocationConstraint="$REGION"
  echo "Created bucket: $BUCKET"
fi

aws s3api put-public-access-block \
  --bucket "$BUCKET" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

aws s3api put-bucket-encryption \
  --bucket "$BUCKET" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

aws s3api put-bucket-versioning \
  --bucket "$BUCKET" \
  --versioning-configuration Status=Suspended

# Auto-delete backups older than RETENTION_DAYS (also cleans incomplete multipart uploads).
aws s3api put-bucket-lifecycle-configuration \
  --bucket "$BUCKET" \
  --lifecycle-configuration "{
    \"Rules\": [
      {
        \"ID\": \"expire-belleliteaccounts-backups-${RETENTION_DAYS}d\",
        \"Status\": \"Enabled\",
        \"Filter\": {\"Prefix\": \"belleliteaccounts/\"},
        \"Expiration\": {\"Days\": ${RETENTION_DAYS}},
        \"AbortIncompleteMultipartUpload\": {\"DaysAfterInitiation\": 1}
      }
    ]
  }"

if aws iam get-user --user-name "$IAM_USER" >/dev/null 2>&1; then
  echo "IAM user already exists: $IAM_USER"
else
  aws iam create-user --user-name "$IAM_USER" \
    --tags Key=Purpose,Value=belleliteaccounts-db-backup Key=App,Value=belleliteaccounts >/dev/null
  echo "Created IAM user: $IAM_USER"
fi

POLICY_DOC=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListBucketPrefix",
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": ["arn:aws:s3:::${BUCKET}"],
      "Condition": {
        "StringLike": {"s3:prefix": ["belleliteaccounts/*"]}
      }
    },
    {
      "Sid": "ObjectRW",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:AbortMultipartUpload"
      ],
      "Resource": ["arn:aws:s3:::${BUCKET}/belleliteaccounts/*"]
    }
  ]
}
EOF
)

aws iam put-user-policy \
  --user-name "$IAM_USER" \
  --policy-name "$POLICY_NAME" \
  --policy-document "$POLICY_DOC"

# Rotate: create a fresh access key (delete oldest if 2 already exist).
KEY_COUNT="$(aws iam list-access-keys --user-name "$IAM_USER" --query 'length(AccessKeyMetadata)' --output text)"
if [[ "$KEY_COUNT" -ge 2 ]]; then
  OLDEST="$(aws iam list-access-keys --user-name "$IAM_USER" \
    --query 'AccessKeyMetadata|sort_by(@,&CreateDate)[0].AccessKeyId' --output text)"
  aws iam delete-access-key --user-name "$IAM_USER" --access-key-id "$OLDEST"
  echo "Deleted oldest access key: $OLDEST"
fi

CREDS_JSON="$(aws iam create-access-key --user-name "$IAM_USER")"
ACCESS_KEY_ID="$(printf '%s' "$CREDS_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["AccessKey"]["AccessKeyId"])')"
SECRET_ACCESS_KEY="$(printf '%s' "$CREDS_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["AccessKey"]["SecretAccessKey"])')"

OUT="$HOME/belleliteaccounts-backup.env"
umask 077
cat > "$OUT" <<EOF
AWS_ACCESS_KEY_ID=${ACCESS_KEY_ID}
AWS_SECRET_ACCESS_KEY=${SECRET_ACCESS_KEY}
AWS_DEFAULT_REGION=${REGION}
BACKUP_S3_BUCKET=${BUCKET}
BACKUP_S3_PREFIX=belleliteaccounts
BACKUP_RETENTION_DAYS=${RETENTION_DAYS}
# Glacier Deep Archive (cheapest storage class; 180-day minimum billable period).
BACKUP_S3_STORAGE_CLASS=DEEP_ARCHIVE
EOF

echo
echo "============================================================"
echo "SUCCESS. Credentials written in CloudShell to:"
echo "  $OUT"
echo
echo "Download that file from CloudShell (Actions → Download file),"
echo "or paste this block back into the Cursor chat (keep it private):"
echo "------------------------------------------------------------"
cat "$OUT"
echo "------------------------------------------------------------"
echo "Then tell the agent: credentials ready"
echo "============================================================"
