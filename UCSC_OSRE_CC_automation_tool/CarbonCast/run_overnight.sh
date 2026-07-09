#!/bin/bash
set -e

PAIRS=(
  "DE wind" "DE temp" "DUK temp"
  "DUK wind" "DOPD temp"
  "DOPD wind" "DK wind"
  "DK temp"
  "DE temp"
)

for pair in "${PAIRS[@]}"; do
  read -r region var <<< "$pair"
  echo "=================================================="
  echo "Starting $region $var at $(date)"
  echo "=================================================="
  python3 gen_and_submit_batch3.py "$region" "$var"
  echo "Finished $region $var at $(date)"
done

echo "ALL REGIONS/VARIABLES COMPLETE at $(date)"
