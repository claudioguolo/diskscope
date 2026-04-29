#!/usr/bin/env bash

set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CAPTURE_FILE="$(mktemp)"
OUTPUT_FILE="$(mktemp)"

cleanup() {
    rm -f "${CAPTURE_FILE}" "${OUTPUT_FILE}"
}

trap cleanup EXIT

chmod +x "${ROOT_DIR}"/tests/mockbin_service/*

PATH="${ROOT_DIR}/tests/mockbin_service:${PATH}" \
MOCK_CURL_CAPTURE="${CAPTURE_FILE}" \
COLLECTOR_URL="http://mock-collector.local/service-alert" \
TOKEN="TOKEN_TESTE" \
bash "${ROOT_DIR}/service_report.sh" >"${OUTPUT_FILE}"

grep -q 'RESULT=OK' "${OUTPUT_FILE}"
grep -q 'SERVICE_COUNT=' "${OUTPUT_FILE}"
grep -q '"status": "OK"' "${CAPTURE_FILE}"
grep -q '"service_count": 7' "${CAPTURE_FILE}"
grep -q '"name":"Nginx"' "${CAPTURE_FILE}"
grep -q '"name":"PostgreSQL"' "${CAPTURE_FILE}"
grep -q '"name":"Docker Engine"' "${CAPTURE_FILE}"
grep -q '"name":"Containers Docker em execucao"' "${CAPTURE_FILE}"
grep -q '"name":"Java Application Service"' "${CAPTURE_FILE}"

printf 'service mock test ok\n'
