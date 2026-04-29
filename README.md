# DiskScope

Coletor de inventario para execucao via Red Hat Satellite.

O projeto agora tem duas trilhas independentes:

- `script.sh`: monitor de discos nao utilizados, mantido no formato atual.
- `service_report.sh`: inventario de servicos ativos para identificar hosts ligados, mas sem carga util detectada.
- `docker-compose.yml`: sobe um coletor HTTP unico com dois endpoints e dois paineis.

## Estrutura

```text
.
├── collector/
│   ├── app.py
│   └── Dockerfile
├── tests/
│   ├── mockbin_service/
│   └── run_service_mock_test.sh
├── tests/
│   ├── mockbin/
│   └── run_mock_test.sh
├── docker-compose.yml
├── README.md
└── script.sh
```

## Parte 1: monitor de discos

O fluxo atual continua igual.

### Script shell

Parametros principais via ambiente:

- `COLLECTOR_URL`: URL completa do endpoint.
- `COLLECTOR_SCHEME`, `COLLECTOR_HOST`, `COLLECTOR_PORT`, `COLLECTOR_PATH`: alternativa para montar a URL.
- `TOKEN`: token de autenticacao.
- `CONNECT_TIMEOUT`, `MAX_TIME`, `RETRY_COUNT`, `RETRY_DELAY`, `RETRY_MAX_TIME`: controles de timeout e retry.
- `PROXY_URL`: proxy HTTP/HTTPS explicito para o `curl`.
- `LOG_ENABLED=1`: habilita log.
- `LOG_FILE=/caminho/arquivo.log`: grava log em arquivo; sem isso, usa `stderr`.

Exemplo de execucao:

```bash
chmod +x script.sh
COLLECTOR_URL="http://coletor.exemplo.local:8000/disk-alert" \
TOKEN="SEU_TOKEN_AQUI" \
LOG_ENABLED=1 \
./script.sh
```

Com proxy:

```bash
PROXY_URL="http://proxy.exemplo.local:3128" ./script.sh
```

Comportamento de retorno:

- `exit 0` quando a coleta termina e o POST HTTP retorna `2xx`, mesmo que existam discos nao utilizados.
- `exit 1` apenas quando o envio HTTP falha ou retorna status fora de `2xx`.

## Uso via Satellite

Exemplo de parametros para um Job Template:

```bash
export COLLECTOR_URL="http://coletor.exemplo.local:8000/disk-alert"
export TOKEN="SEU_TOKEN_AQUI"
export CONNECT_TIMEOUT="10"
export MAX_TIME="30"
export RETRY_COUNT="3"
export RETRY_DELAY="2"
export RETRY_MAX_TIME="60"
export PROXY_URL=""
export LOG_ENABLED="0"

/bin/bash /caminho/script.sh
```

O script imprime uma linha final em formato simples, adequada para leitura no resultado do job:

```text
RESULT=ATENCAO UNUSED_DISKS=/dev/sdb UNUSED_CAPACITY=53.7 GB HTTP_CODE=200 DETECTION_STATE=ok
```

## Parte 2: inventario de servicos do host

O novo fluxo segue a mesma ideia do monitor de disco, mas envia um retrato do que o host esta efetivamente executando.

Ele tenta identificar:

- servidores web como Apache, Nginx, HAProxy e Traefik
- bancos e caches como PostgreSQL, MySQL/MariaDB, MongoDB e Redis
- runtimes e workloads de containers como Docker, containerd, Podman e kubelet
- mensageria como RabbitMQ

O host recebe `WARNING` quando nenhum servico relevante e detectado. Isso ajuda a localizar maquinas ligadas sem aplicacao, banco, container ou fila em uso aparente.

### Script shell de servicos

Parametros principais via ambiente:

- `COLLECTOR_URL`: URL completa do endpoint.
- `COLLECTOR_SCHEME`, `COLLECTOR_HOST`, `COLLECTOR_PORT`, `COLLECTOR_PATH`: alternativa para montar a URL.
- `TOKEN`: token de autenticacao.
- `CONNECT_TIMEOUT`, `MAX_TIME`, `RETRY_COUNT`, `RETRY_DELAY`, `RETRY_MAX_TIME`: controles de timeout e retry.
- `PROXY_URL`: proxy HTTP/HTTPS explicito para o `curl`.
- `LOG_ENABLED=1`: habilita log.
- `LOG_FILE=/caminho/arquivo.log`: grava log em arquivo; sem isso, usa `stderr`.

Exemplo de execucao:

```bash
chmod +x service_report.sh
COLLECTOR_URL="http://coletor.exemplo.local:8000/service-alert" \
TOKEN="SEU_TOKEN_AQUI" \
LOG_ENABLED=1 \
./service_report.sh
```

Exemplo de retorno:

```text
RESULT=OK SERVICE_COUNT=4 SERVICES=Nginx,PostgreSQL,Docker Engine,Containers Docker em execucao HTTP_CODE=200 DETECTION_STATE=ok
```

## Coletor containerizado

Subir o coletor:

```bash
cp .env.example .env
docker compose up -d --build
```

Validar saude:

```bash
curl -s http://127.0.0.1:8000/health
```

Abrir os paineis:

```bash
curl -s http://127.0.0.1:8000/
curl -s http://127.0.0.1:8000/services
```

No navegador, acessar:

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/services
```

Endpoints de ingestao:

- discos: `/disk-alert`
- servicos: `/service-alert`

Os payloads recebidos ficam em:

- `./data/requests.jsonl` para discos
- `./data/service-requests.jsonl` para servicos

Cada linha contem um JSON com:

- horario de recebimento
- IP remoto
- payload original enviado pelo script correspondente

Na interface web, o painel tambem mostra:

- em discos: percentual de hosts com ocorrencia e capacidade total nao utilizada
- em servicos: hosts sem servicos detectados, total de servicos mapeados e media por host

## Testes locais

Teste rapido do script com mocks:

```bash
bash tests/run_mock_test.sh
bash tests/run_service_mock_test.sh
```

## Template visual

Este repositorio tambem inclui templates de tema reutilizavel inspirados no projeto `rvscope`:

- [rvscope-theme.css](/home/claudio/Docker/coletor_disco/ui/rvscope-theme.css)
- [rvscope-theme-dashboard.html](/home/claudio/Docker/coletor_disco/templates/rvscope-theme-dashboard.html)
- [rvscope-bootstrap-theme.css](/home/claudio/Docker/coletor_disco/ui/rvscope-bootstrap-theme.css)
- [rvscope-bootstrap-dashboard.html](/home/claudio/Docker/coletor_disco/templates/rvscope-bootstrap-dashboard.html)
- [THEME_GUIDE.md](/home/claudio/Docker/coletor_disco/ui/THEME_GUIDE.md)

Ele foi pensado para dashboards de coleta e relatorios, com:

- header hero padronizado
- cards de metricas
- barras de filtro
- tabela compacta
- badges de status
- versao pronta em Bootstrap para reaproveitamento rapido

## Publicacao no GitHub

Antes de subir:

- ajuste os valores de exemplo de token e URL para o seu ambiente
- mantenha fora do repositorio qualquer dado real em `data/` e arquivos `.env`
- revise se deseja incluir uma `LICENSE`

Fluxo minimo:

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin <URL_DO_REPOSITORIO>
git push -u origin main
```
