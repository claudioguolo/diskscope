# DiskScope Theme Kit

Template visual reutilizavel, inspirado no projeto `rvscope`, para dashboards de coleta, relatorios operacionais e telas de inventario.

## Arquivos

- `ui/rvscope-theme.css`: versao CSS pura, sem framework.
- `templates/rvscope-theme-dashboard.html`: pagina modelo da versao CSS pura.
- `ui/rvscope-bootstrap-theme.css`: versao baseada em Bootstrap.
- `templates/rvscope-bootstrap-dashboard.html`: pagina modelo da versao Bootstrap.

## Identidade visual herdada do rvscope

- fonte de destaque: `Space Grotesk`
- fonte de leitura: `Source Sans 3`
- gradiente principal azul-petroleo
- cards brancos com borda suave e sombra discreta
- tabelas com cabecalho escuro e foco em legibilidade

## Componentes padronizados

- `page-shell`: largura e respiro da pagina
- `app-header`: cabecalho hero com nome e subtitulo
- `app-card`: container base para blocos
- `metrics-grid`: cards de indicadores
- `toolbar` e `toolbar-form`: acoes e filtros
- `data-table`: tabela padrao para listagens
- `badge-*`: indicadores de estado
- `empty-state`: estado vazio padronizado

## Como usar

### Opcao recomendada: Bootstrap

1. Copie `templates/rvscope-bootstrap-dashboard.html`.
2. Substitua placeholders como `{{ APP_NAME }}` e `{{ PAGE_TITLE }}`.
3. Mantenha os `links` para Bootstrap, Google Fonts e `ui/rvscope-bootstrap-theme.css`.
4. Preencha os blocos com os dados da sua aplicacao.

### Opcao sem framework

1. Copie `templates/rvscope-theme-dashboard.html`.
2. Mantenha o `link` para `ui/rvscope-theme.css`.
3. Preencha os blocos com os dados da sua aplicacao.

## Recomendacao

Se voce tiver mais de uma aplicacao Python/PHP/HTML, mantenha uma das versoes como base unica e adapte apenas o conteudo da pagina. Para telas CRUD, filtros, modais e tabelas, a versao Bootstrap tende a ser a mais pratica no dia a dia.
