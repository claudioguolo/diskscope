#!/usr/bin/env bash

set -u


readonly SCRIPT_NAME="$(basename "$0")"
readonly DEFAULT_CONNECT_TIMEOUT=10
readonly DEFAULT_MAX_TIME=30
readonly DEFAULT_RETRY_COUNT=3
readonly DEFAULT_RETRY_DELAY=2
readonly DEFAULT_RETRY_MAX_TIME=60
readonly DEFAULT_COLLECTOR_PATH="/service-alert"

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

join_json_array_raw() {
    local result=""
    local item

    for item in "$@"; do
        if [ -n "$result" ]; then
            result="${result},"
        fi
        result="${result}${item}"
    done

    printf '[%s]' "$result"
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

format_status_label() {
    case "${1:-}" in
        WARNING) printf 'ATENCAO' ;;
        OK) printf 'OK' ;;
        *) printf '%s' "${1:-UNKNOWN}" ;;
    esac
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

collect_metadata() {
    HOSTNAME_FQDN="$(hostname -f 2>/dev/null || hostname 2>/dev/null || printf 'unknown-host')"
    IP_ADDR="$(hostname -I 2>/dev/null | awk '{print $1}')"
    DATE_UTC="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    OS_NAME="$(grep '^PRETTY_NAME=' /etc/os-release 2>/dev/null | cut -d= -f2- | tr -d '"')"

    [ -n "$IP_ADDR" ] || IP_ADDR="unknown"
    [ -n "$OS_NAME" ] || OS_NAME="unknown"
}

append_service() {
    local category="$1"
    local service_name="$2"
    local evidence="$3"
    local detail

    detail="${category}|${service_name}"
    if printf '%s\n' "${SERVICE_KEYS[@]}" | grep -Fxq "$detail"; then
        return 0
    fi

    SERVICE_KEYS+=("$detail")
    SERVICE_DETAILS+=("{\"category\":\"$(json_escape "$category")\",\"name\":\"$(json_escape "$service_name")\",\"evidence\":\"$(json_escape "$evidence")\"}")
    SERVICE_CATEGORIES+=("$category")
    SERVICE_NAMES+=("$service_name")
}

systemctl_is_active() {
    local unit="$1"
    systemctl is-active --quiet "$unit" 2>/dev/null
}

process_exists() {
    local pattern="$1"
    ps -eo comm= 2>/dev/null | grep -Eiq "$pattern"
}

socket_exists() {
    local pattern="$1"
    ss -lntup 2>/dev/null | grep -Eiq "$pattern"
}

detect_web_services() {
    if command_exists systemctl; then
        systemctl_is_active "httpd.service" && append_service "web" "Apache HTTP Server" "systemd:httpd.service"
        systemctl_is_active "nginx.service" && append_service "web" "Nginx" "systemd:nginx.service"
        systemctl_is_active "haproxy.service" && append_service "web" "HAProxy" "systemd:haproxy.service"
        systemctl_is_active "traefik.service" && append_service "web" "Traefik" "systemd:traefik.service"
    else
        DETECTION_ERRORS+=("systemctl_not_found")
    fi

    if command_exists ps; then
        process_exists '^(httpd|apache2)$' && append_service "web" "Apache HTTP Server" "process:httpd"
        process_exists '^nginx$' && append_service "web" "Nginx" "process:nginx"
        process_exists '^haproxy$' && append_service "web" "HAProxy" "process:haproxy"
        process_exists '^traefik$' && append_service "web" "Traefik" "process:traefik"
    else
        DETECTION_ERRORS+=("ps_not_found")
    fi

    if command_exists ss; then
        socket_exists ':(80|443|8080|8443)\b' && append_service "web" "Listener HTTP/HTTPS" "socket:80,443,8080,8443"
    else
        DETECTION_ERRORS+=("ss_not_found")
    fi
}

detect_java_services() {
    if command_exists systemctl; then
        systemctl_is_active "jboss.service" && append_service "java" "JBoss" "systemd:jboss.service"
        systemctl_is_active "wildfly.service" && append_service "java" "WildFly" "systemd:wildfly.service"
        systemctl_is_active "tomcat.service" && append_service "java" "Tomcat" "systemd:tomcat.service"
        systemctl_is_active "tomcat9.service" && append_service "java" "Tomcat" "systemd:tomcat9.service"
        systemctl_is_active "tomcat10.service" && append_service "java" "Tomcat" "systemd:tomcat10.service"
    fi

    if command_exists ps; then
        process_exists '^(jboss|wildfly)$' && append_service "java" "JBoss/WildFly" "process:jboss|wildfly"
        process_exists '^tomcat$' && append_service "java" "Tomcat" "process:tomcat"
        process_exists '^java$' && append_service "java" "Java Application Service" "process:java"

        if ps -eo args= 2>/dev/null | grep -Eiq '(org\.jboss|wildfly|catalina\.start|tomcat|java .*-jar)'; then
            append_service "java" "Java Application Service" "process_args:java"
        fi
    fi

    if command_exists ss; then
        socket_exists ':(8080|8443|9990)\b' && append_service "java" "Java Application Listener" "socket:8080,8443,9990"
    fi
}

detect_database_services() {
    if command_exists systemctl; then
        systemctl_is_active "mysqld.service" && append_service "database" "MySQL/MariaDB" "systemd:mysqld.service"
        systemctl_is_active "mariadb.service" && append_service "database" "MySQL/MariaDB" "systemd:mariadb.service"
        systemctl_is_active "postgresql.service" && append_service "database" "PostgreSQL" "systemd:postgresql.service"
        systemctl_is_active "mongod.service" && append_service "database" "MongoDB" "systemd:mongod.service"
        systemctl_is_active "redis.service" && append_service "cache" "Redis" "systemd:redis.service"
        systemctl_is_active "redis-server.service" && append_service "cache" "Redis" "systemd:redis-server.service"
    fi

    if command_exists ps; then
        process_exists '^(mysqld|mariadbd)$' && append_service "database" "MySQL/MariaDB" "process:mysqld"
        process_exists '^postgres$' && append_service "database" "PostgreSQL" "process:postgres"
        process_exists '^mongod$' && append_service "database" "MongoDB" "process:mongod"
        process_exists '^redis-server$' && append_service "cache" "Redis" "process:redis-server"
    fi

    if command_exists ss; then
        socket_exists ':(3306|5432|27017|6379)\b' && append_service "database" "Listener de banco/cache" "socket:3306,5432,27017,6379"
    fi
}

detect_container_services() {
    local docker_count="0"

    if command_exists systemctl; then
        systemctl_is_active "docker.service" && append_service "container" "Docker Engine" "systemd:docker.service"
        systemctl_is_active "containerd.service" && append_service "container" "containerd" "systemd:containerd.service"
        systemctl_is_active "podman.service" && append_service "container" "Podman" "systemd:podman.service"
        systemctl_is_active "kubelet.service" && append_service "orchestration" "Kubernetes Kubelet" "systemd:kubelet.service"
    fi

    if command_exists docker; then
        docker_count="$(docker ps -q 2>/dev/null | awk 'NF {count++} END {print count+0}')"
        if [ "$docker_count" -gt 0 ]; then
            append_service "container" "Containers Docker em execucao" "docker_ps:${docker_count}"
        fi
    else
        DETECTION_ERRORS+=("docker_not_found")
    fi

    if command_exists ps; then
        process_exists '^dockerd$' && append_service "container" "Docker Engine" "process:dockerd"
        process_exists '^containerd$' && append_service "container" "containerd" "process:containerd"
        process_exists '^podman$' && append_service "container" "Podman" "process:podman"
        process_exists '^kubelet$' && append_service "orchestration" "Kubernetes Kubelet" "process:kubelet"
    fi

    if command_exists ss; then
        socket_exists ':(2375|2376|6443)\b' && append_service "container" "Listener Docker/Kubernetes" "socket:2375,2376,6443"
    fi
}

detect_message_services() {
    if command_exists systemctl; then
        systemctl_is_active "rabbitmq-server.service" && append_service "messaging" "RabbitMQ" "systemd:rabbitmq-server.service"
    fi

    if command_exists ps; then
        process_exists '^rabbitmq-server$' && append_service "messaging" "RabbitMQ" "process:rabbitmq-server"
    fi

    if command_exists ss; then
        socket_exists ':(5672|15672|9092)\b' && append_service "messaging" "Listener de mensageria" "socket:5672,15672,9092"
    fi
}

collect_service_inventory() {
    SERVICE_KEYS=()
    SERVICE_DETAILS=()
    SERVICE_CATEGORIES=()
    SERVICE_NAMES=()
    DETECTION_ERRORS=()

    detect_web_services
    detect_java_services
    detect_database_services
    detect_container_services
    detect_message_services
}

build_payload() {
    local status="$1"
    local detection_state="$2"
    local services_json categories_json names_json errors_json

    services_json="$(join_json_array_raw "${SERVICE_DETAILS[@]}")"
    categories_json="$(join_json_array "${SERVICE_CATEGORIES[@]}")"
    names_json="$(join_json_array "${SERVICE_NAMES[@]}")"
    errors_json="$(join_json_array "${DETECTION_ERRORS[@]}")"

    cat <<EOF
{
  "hostname": "$(json_escape "$HOSTNAME_FQDN")",
  "ip": "$(json_escape "$IP_ADDR")",
  "os": "$(json_escape "$OS_NAME")",
  "timestamp": "$(json_escape "$DATE_UTC")",
  "status": "$(json_escape "$status")",
  "detection_state": "$(json_escape "$detection_state")",
  "service_count": ${#SERVICE_DETAILS[@]},
  "service_categories": $categories_json,
  "service_names": $names_json,
  "services": $services_json,
  "detection_errors": $errors_json
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
    local collector_url status status_label detection_state payload service_csv="none"

    collect_metadata
    collect_service_inventory
    collector_url="$(build_collector_url)"
    CURL_RC=0
    HTTP_CODE=0

    if [ "${#DETECTION_ERRORS[@]}" -gt 0 ]; then
        detection_state="degraded"
    else
        detection_state="ok"
    fi

    if [ "${#SERVICE_DETAILS[@]}" -gt 0 ]; then
        status="OK"
        service_csv="$(IFS=,; printf '%s' "${SERVICE_NAMES[*]}")"
    else
        status="WARNING"
    fi
    status_label="$(format_status_label "$status")"

    payload="$(build_payload "$status" "$detection_state")"

    if ! send_payload "$payload" "$collector_url"; then
        exit 1
    fi

    printf 'RESULT=%s SERVICE_COUNT=%s SERVICES=%s HTTP_CODE=%s DETECTION_STATE=%s\n' \
        "$status_label" "${#SERVICE_DETAILS[@]}" "$service_csv" "$HTTP_CODE" "$detection_state"
    exit 0
}

main "$@"
