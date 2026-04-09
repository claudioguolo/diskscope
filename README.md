# noused_disc

Coletor de discos nao utilizados para execucao via Red Hat Satellite.

Projeto com duas partes:

- `script.sh`: script Bash para rodar via Red Hat Satellite e identificar discos nao utilizados.
- `docker-compose.yml`: sobe um coletor HTTP simples para receber os JSONs enviados pelo script.

## Estrutura

```text
.
├── collector/
│   ├── app.py
│   └── Dockerfile
├── tests/
│   ├── mockbin/
│   └── run_mock_test.sh
├── docker-compose.yml
├── README.md
└── script.sh
```

## Script shell

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
RESULT=WARNING UNUSED_DISKS=/dev/sdb HTTP_CODE=200 DETECTION_STATE=ok
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

Abrir a interface web com tabela dos dados coletados:

```bash
curl -s http://127.0.0.1:8000/
```

No navegador, acessar:

```text
http://127.0.0.1:8000/
```

Os payloads recebidos ficam em:

- `./data/requests.jsonl`

Cada linha contem um JSON com:

- horario de recebimento
- IP remoto
- payload original enviado pelo script

## Testes locais

Teste rapido do script com mocks:

```bash
bash tests/run_mock_test.sh
```

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
