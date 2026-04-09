#!/usr/bin/env bash

set -u


readonly SCRIPT_NAME="$(basename "$0")"
readonly DEFAULT_CONNECT_TIMEOUT=10
readonly DEFAULT_MAX_TIME=30
readonly DEFAULT_RETRY_COUNT=3
readonly DEFAULT_RETRY_DELAY=2
readonly DEFAULT_RETRY_MAX_TIME=60
readonly DEFAULT_COLLECTOR_PATH="/disk-alert"

COLLECTOR_URL="${COLLECTOR_URL:-}"
COLLECTOR_SCHEME="${COLLECTOR_SCHEME:-http}"
COLLECTOR_HOST="${COLLECTOR_HOST:-127.0.0.1}"
COLLECTOR_PORT="${COLLECTOR_PORT:-8000}"
COLLECTOR_PATH="${COLLECTOR_PATH:-$DEFAULT_COLLECTOR_PATH}"
TOKEN="${TOKEN:-}"
AUTH_HEADER_NAME="${AUTH_HEADER_NAME:-Authorization}"
AUTH_HEADER_PREFIX="${AUTH_HEADER_PREFIX:-Bearer}"

CONNECT_TIMEOUT="${CONNECT_TIMEOUT:-$DEFAULT_CONNECT_TIMEOUT}"
MAX_TIME="${MAX_TIME:-$DEFAULT_MAX_TIME}"
RETRY_COUNT="${RETRY_COUNT:-$DEFAULT_RETRY_COUNT}"
RETRY_DELAY="${RETRY_DELAY:-$DEFAULT_RETRY_DELAY}"
RETRY_MAX_TIME="${RETRY_MAX_TIME:-$DEFAULT_RETRY_MAX_TIME}"

PROXY_URL="${PROXY_URL:-}"
LOG_ENABLED="${LOG_ENABLED:-0}"
LOG_FILE="${LOG_FILE:-}"
TMPDIR_BASE="${TMPDIR:-/tmp}"

readonly HTTP_OUTPUT_FILE="${TMPDIR_BASE%/}/${SCRIPT_NAME}.http.out"

log() {
    if [ "$LOG_ENABLED" != "1" ]; then
        return 0
    fi

    local level="$1"
    shift
    local timestamp
    timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

    if [ -n "$LOG_FILE" ]; then
        printf '%s [%s] %s\n' "$timestamp" "$level" "$*" >>"$LOG_FILE"
    else
        printf '%s [%s] %s\n' "$timestamp" "$level" "$*" >&2
    fi
}

json_escape() {
    local value="${1:-}"
    value="${value//\\/\\\\}"
    value="${value//\"/\\\"}"
    value="${value//$'\n'/\\n}"
    value="${value//$'\r'/\\r}"
    value="${value//$'\t'/\\t}"
    printf '%s' "$value"
}

join_json_array() {
    local result=""
    local item

    for item in "$@"; do
        if [ -n "$result" ]; then
            result="${result},"
        fi
        result="${result}\"$(json_escape "$item")\""
    done

    printf '[%s]' "$result"
}

build_collector_url() {
    local path="$COLLECTOR_PATH"

    if [ -n "$COLLECTOR_URL" ]; then
        printf '%s' "$COLLECTOR_URL"
        return 0
    fi

    case "$path" in
        /*) ;;
        *) path="/$path" ;;
    esac

    printf '%s://%s:%s%s' "$COLLECTOR_SCHEME" "$COLLECTOR_HOST" "$COLLECTOR_PORT" "$path"
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

has_children() {
    local disk="$1"
    local child_count

    child_count="$(lsblk -n -o NAME "$disk" 2>/dev/null | sed '1d' | wc -l | tr -d ' ')"
    [ "${child_count:-0}" -gt 0 ]
}

disk_has_mountpoint() {
    local disk="$1"
    lsblk -n -o MOUNTPOINT "$disk" 2>/dev/null | grep -q '[^[:space:]]'
}

disk_has_filesystem_signature() {
    local disk="$1"
    blkid "$disk" >/dev/null 2>&1
}

disk_in_lvm() {
    local disk="$1"
    command_exists pvs || return 1
    pvs --noheadings -o pv_name 2>/dev/null | awk '{print $1}' | grep -Fxq "$disk"
}

disk_in_swap() {
    local disk="$1"
    command_exists swapon || return 1
    swapon --noheadings --raw 2>/dev/null | awk '{print $1}' | grep -Fxq "$disk"
}

disk_in_mdraid() {
    local disk="$1"
    command_exists mdadm || return 1
    mdadm --examine "$disk" >/dev/null 2>&1
}

disk_is_unused() {
    local disk="$1"

    has_children "$disk" && return 1
    disk_has_mountpoint "$disk" && return 1
    disk_has_filesystem_signature "$disk" && return 1
    disk_in_lvm "$disk" && return 1
    disk_in_swap "$disk" && return 1
    disk_in_mdraid "$disk" && return 1

    return 0
}

collect_metadata() {
    HOSTNAME_FQDN="$(hostname -f 2>/dev/null || hostname 2>/dev/null || printf 'unknown-host')"
    IP_ADDR="$(hostname -I 2>/dev/null | awk '{print $1}')"
    DATE_UTC="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    OS_NAME="$(grep '^PRETTY_NAME=' /etc/os-release 2>/dev/null | cut -d= -f2- | tr -d '"')"

    [ -n "$IP_ADDR" ] || IP_ADDR="unknown"
    [ -n "$OS_NAME" ] || OS_NAME="unknown"
}

collect_unused_disks() {
    local line name type disk

    UNUSED_DISKS=()

    if ! command_exists lsblk; then
        DETECTION_ERRORS+=("lsblk_not_found")
        log "WARN" "lsblk nao encontrado; coleta de discos indisponivel."
        return 0
    fi

    while read -r line; do
        name="${line%% *}"
        type="${line##* }"

        [ "$type" = "disk" ] || continue
        disk="/dev/$name"

        if disk_is_unused "$disk"; then
            UNUSED_DISKS+=("$disk")
            log "INFO" "Disco nao utilizado identificado: $disk"
        fi
    done < <(lsblk -dn -e 7,11 -o NAME,TYPE 2>/dev/null)
}

build_payload() {
    local status="$1"
    local detection_state="$2"
    local unused_json detection_json

    unused_json="$(join_json_array "${UNUSED_DISKS[@]}")"
    detection_json="$(join_json_array "${DETECTION_ERRORS[@]}")"

    cat <<EOF
{
  "hostname": "$(json_escape "$HOSTNAME_FQDN")",
  "ip": "$(json_escape "$IP_ADDR")",
  "os": "$(json_escape "$OS_NAME")",
  "timestamp": "$(json_escape "$DATE_UTC")",
  "status": "$(json_escape "$status")",
  "detection_state": "$(json_escape "$detection_state")",
  "unused_disks": $unused_json,
  "unused_disks_count": ${#UNUSED_DISKS[@]},
  "detection_errors": $detection_json
}
EOF
}

send_payload() {
    local payload="$1"
    local url="$2"
    local -a curl_args
    local http_code

    if ! command_exists curl; then
        log "ERROR" "curl nao encontrado; envio HTTP impossivel."
        printf 'RESULT=ERROR MSG=http_client_not_found\n'
        return 1
    fi

    curl_args=(
        --silent
        --show-error
        --output "$HTTP_OUTPUT_FILE"
        --write-out "%{http_code}"
        --request POST
        --header "Content-Type: application/json"
        --data "$payload"
        --connect-timeout "$CONNECT_TIMEOUT"
        --max-time "$MAX_TIME"
        --retry "$RETRY_COUNT"
        --retry-delay "$RETRY_DELAY"
        --retry-max-time "$RETRY_MAX_TIME"
    )

    if [ -n "$TOKEN" ]; then
        curl_args+=(--header "${AUTH_HEADER_NAME}: ${AUTH_HEADER_PREFIX} ${TOKEN}")
    fi

    if [ -n "$PROXY_URL" ]; then
        curl_args+=(--proxy "$PROXY_URL")
        log "INFO" "Envio HTTP usando proxy explicito."
    fi

    log "INFO" "Enviando payload para $url"
    http_code="$(curl "${curl_args[@]}" "$url")"
    CURL_RC=$?

    if [ "$CURL_RC" -ne 0 ]; then
        log "ERROR" "Falha no POST HTTP. curl_rc=$CURL_RC"
        printf 'RESULT=ERROR MSG=http_post_failed CURL_RC=%s\n' "$CURL_RC"
        return 1
    fi

    if [ "${http_code:-000}" -lt 200 ] || [ "${http_code:-000}" -ge 300 ]; then
        log "ERROR" "Resposta HTTP fora da faixa de sucesso. http_code=$http_code"
        printf 'RESULT=ERROR MSG=http_bad_status HTTP_CODE=%s\n' "$http_code"
        return 1
    fi

    HTTP_CODE="$http_code"
    log "INFO" "Payload entregue com sucesso. http_code=$HTTP_CODE"
    return 0
}

main() {
    local collector_url status detection_state payload unused_csv="none"

    UNUSED_DISKS=()
    DETECTION_ERRORS=()
    CURL_RC=0
    HTTP_CODE=0

    collect_metadata
    collector_url="$(build_collector_url)"
    collect_unused_disks

    if [ "${#DETECTION_ERRORS[@]}" -gt 0 ]; then
        detection_state="degraded"
    else
        detection_state="ok"
    fi

    if [ "${#UNUSED_DISKS[@]}" -gt 0 ]; then
        status="WARNING"
        unused_csv="$(IFS=,; printf '%s' "${UNUSED_DISKS[*]}")"
    else
        status="OK"
    fi

    payload="$(build_payload "$status" "$detection_state")"

    if ! send_payload "$payload" "$collector_url"; then
        exit 1
    fi

    printf 'RESULT=%s UNUSED_DISKS=%s HTTP_CODE=%s DETECTION_STATE=%s\n' \
        "$status" "$unused_csv" "$HTTP_CODE" "$detection_state"
    exit 0
}

main "$@"
