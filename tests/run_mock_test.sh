#!/usr/bin/env bash

set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CAPTURE_FILE="${ROOT_DIR}/tests/mock_payload.json"
OUTPUT_FILE="${ROOT_DIR}/tests/mock_output.txt"

chmod +x "${ROOT_DIR}"/tests/mockbin/*

PATH="${ROOT_DIR}/tests/mockbin:${PATH}" \
MOCK_CURL_CAPTURE="${CAPTURE_FILE}" \
COLLECTOR_URL="http://mock-collector.local/disk-alert" \
TOKEN="TOKEN_TESTE" \
bash "${ROOT_DIR}/script.sh" >"${OUTPUT_FILE}"

grep -q 'RESULT=ATENCAO' "${OUTPUT_FILE}"
grep -q 'UNUSED_DISKS=/dev/sdb' "${OUTPUT_FILE}"
grep -q 'UNUSED_CAPACITY=53.7 GB' "${OUTPUT_FILE}"
grep -q '"unused_disks_count": 1' "${CAPTURE_FILE}"
grep -q '"status": "WARNING"' "${CAPTURE_FILE}"
grep -q '"unused_capacity_total_bytes": 53687091200' "${CAPTURE_FILE}"

printf 'mock test ok\n'
