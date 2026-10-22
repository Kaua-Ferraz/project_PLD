# Coleta incremental de dados CKAN

Este documento descreve o componente responsável por coletar recursos CSV dos portais de dados abertos da CCEE e do ONS. O fluxo foi desenhado para que uma falha de rede, um CSV inválido ou um manifesto incompleto não destrua a última versão válida.

[Voltar ao README principal](../README.md)

Esta etapa termina nos arquivos brutos de `data/raw/`. O coletor verifica se o
arquivo recebido é utilizável, mas não o adapta para o modelo e não agrega dados.
A padronização das colunas, a agregação diária e a geração dos arquivos Parquet
são explicadas em [Limpeza e transformação dos dados](limpeza_transformacao.md).

## Datasets coletados

| Portal | Identificador do dataset | Conteúdo |
| --- | --- | --- |
| CCEE | `pld_media_diaria` | PLD médio diário por submercado |
| CCEE | `pld_horario` | PLD horário por submercado |
| ONS | `carga-energia` | carga de energia diária por subsistema |
| ONS | `ear-diario-por-subsistema` | Energia Armazenada diária |
| ONS | `ena-diario-por-subsistema` | Energia Natural Afluente diária |
| ONS | `balanco-energia-subsistema` | balanço horário de energia por subsistema |

Os nomes acima são os identificadores usados pelos respectivos portais CKAN. Os
recursos anuais selecionados pelo coletor são preservados como CSV, sem correção
silenciosa de valores.

## Como estudar a implementação

O fluxo original do coletor foi mantido de propósito. A melhor ordem de leitura é:

1. Abra `src/pld_forecast/collectors/ccee.py`. Observe o laço que cria `CKANClient`, chama `get_resources()` e depois chama `download_resource()` para cada CSV.
2. Leia `get_resources()` em `src/pld_forecast/collectors/ckan.py`. Ele faz uma requisição para `package_show`, valida o JSON e reutiliza a sessão HTTP.
3. Leia `download_resource()` aos poucos. O método está dividido por comentários: decisão de baixar, download temporário, comparação de hash, validação, backup e troca.
4. Por fim, abra `src/pld_forecast/collectors/validate.py`. As validações foram deixadas fora do cliente porque o cliente CKAN não deve conhecer regras exclusivas do PLD.
5. Leia `snapshots.py` para ver como uma cópia capturada recebe horário, hash e maior referência realmente presente no CSV.

As funções retornam dicionários simples. Por exemplo, um download retorna `{"status": "downloaded", "path": ..., "backup": ...}`. Isso evita uma hierarquia de classes e permite inspecionar os valores com facilidade durante o estudo ou pelo depurador.

## Instalação e comandos

Execute os comandos a partir da raiz do projeto:

```powershell
python -m pip install -e ".[dev]"

# Todos os CSVs desde 2021 e recursos acumulados sem ano no nome ou URL
pld collect historical --snapshot

# Recursos do ano atual e recursos acumulados
pld collect daily --snapshot

# Ignora o cache e confirma novamente pelo conteúdo
pld collect daily --force --snapshot

# Limita a execução a um portal
pld collect daily --portal ccee --snapshot
pld collect historical --portal ons --snapshot

# Testes sem dependência obrigatória dos portais externos
python -m pytest -q
```

O diretório de dados pode ser alterado com `--data-dir`. O primeiro ano da coleta histórica pode ser alterado com `--start-year`. Os comandos antigos `python -m src.update` continuam disponíveis.

## Estrutura do coletor

```text
src/pld_forecast/
├── collectors/
│   ├── ckan.py       # HTTP, manifesto, hash, backup e troca atômica
│   ├── ccee.py       # PLD diário e horário
│   ├── ons.py        # datasets do ONS
│   ├── validate.py   # validação geral e específica do PLD
│   └── snapshots.py  # cópias e metadados ex ante
└── cli.py             # comando pld

tests/                 # testes com sessões e respostas HTTP simuladas

data/
├── manifest.json
├── snapshots/<YYYY-MM-DD_HHMMSS>/
└── raw/<portal>/<dataset>/
    ├── current/
    └── backups/
```

## Como uma atualização é decidida

1. A lista atual de recursos é obtida por `package_show`.
2. A chave estável no manifesto é `portal:dataset_id:resource_id`.
3. O arquivo local é conferido por tamanho e SHA-256. Uma alteração local dispara uma nova verificação.
4. `last_modified`, `size` e `hash` do CKAN são tratados como sinais de conteúdo. `metadata_modified` sozinho é apenas descritivo e não dispara uma falsa atualização.
5. Quando existem `ETag` ou `Last-Modified` HTTP, eles são enviados em uma requisição condicional. Alguns servidores ignoram esses cabeçalhos; nesse caso, o arquivo recebido ainda é comparado por SHA-256.
6. Quando o portal não oferece nenhum sinal confiável, o arquivo é baixado para uma área temporária. O hash decide se houve mudança. O modo `--force` sempre segue esse caminho.

O download usa streaming e um arquivo temporário no mesmo sistema de arquivos do destino. Respostas HTML ou JSON disfarçadas, arquivos vazios e CSVs inválidos são rejeitados antes de tocar na versão atual.

Erros HTTP 429, 500, 502, 503 e 504 e falhas transitórias de rede recebem novas tentativas com espera progressiva e respeito a `Retry-After`. Erros de autorização não entram em repetição infinita.

## Manifesto local

O arquivo `data/manifest.json` registra, para cada recurso:

- portal e dataset de origem;
- ID estável do recurso;
- URL e nome do arquivo;
- última verificação e último download;
- metadados CKAN relevantes;
- `ETag` e `Last-Modified` HTTP, quando disponíveis;
- tamanho local;
- SHA-256;
- caminho do arquivo;
- resultado detalhado da validação.

O manifesto é salvo em um arquivo temporário antes de substituir o JSON oficial. Se um manifesto estiver corrompido, ele é preservado como `manifest.json.corrupt-<timestamp>`.

## Backups e recuperação

Quando o hash mudou e a nova versão passou na validação, a versão atual é copiada para `backups/` com um timestamp. Em seguida, `os.replace()` instala o arquivo temporário atomicamente.

Se a gravação do manifesto falhar depois da instalação, o arquivo anterior é restaurado do backup. Os backups não são apagados automaticamente nesta versão.

## Validação geral dos CSVs

Antes da instalação, são verificados:

- existência e tamanho do arquivo;
- conteúdo HTML ou JSON disfarçado de CSV;
- encoding e separador;
- cabeçalho;
- quantidade mínima de colunas;
- existência de linhas de dados;
- erros graves de leitura pelo Pandas.

Os validadores retornam erros fatais e avisos separadamente. Erros impedem a substituição. Avisos são registrados, mas permitem preservar o arquivo bruto.

## Validação do PLD

O esquema confirmado no recurso real da CCEE é:

```text
MES_REFERENCIA;SUBMERCADO;DIA;PLD_MEDIA_DIA
```

Além das regras gerais, são verificados:

- colunas obrigatórias;
- datas válidas;
- PLD numérico;
- submercados Norte, Nordeste, Sudeste e Sul;
- chave lógica `DIA + SUBMERCADO`;
- valores ausentes;
- coerência entre `MES_REFERENCIA` e `DIA`;
- lacunas temporais e dias com menos de quatro submercados.

Valores extremos não são removidos automaticamente.

### PLD horário

O esquema foi conferido no [dicionário do PLD horário da CCEE](https://dadosabertos.ccee.org.br/dataset/pld_horario/resource/3f279d6b-1069-42f7-9b0a-217b084729c4).

O dataset horário publica `MES_REFERENCIA`, `SUBMERCADO`,
`PERIODO_COMERCIALIZACAO`, `DIA`, `HORA` e `PLD_HORA` (R$/MWh). `DIA` pode vir
como dia do mês ou como `DD/MM/AAAA`; a limpeza interpreta ambas as formas
usando `MES_REFERENCIA`. `HORA` precisa ser inteira entre 0 e 23. A chave
lógica é `instante + submercado`. Cópias idênticas recebem a mesma flag e o
mesmo sufixo de aviso do PLD diário; preços conflitantes bloqueiam o download.
Lacunas horárias são registradas como avisos e permanecem ausentes.

### Snapshots

Com `--snapshot`, cada recurso selecionado e aceito é copiado para uma pasta
nova, cujo nome contém o horário UTC da execução. O arquivo JSON ao lado
registra `collection_time` (captura), `portal`, `dataset_id`, `resource_id`,
`sha256`, `etag`, `last_modified` e `max_reference_time` (maior instante
realmente presente no CSV). A gravação exclusiva impede substituir uma cópia
anterior. Um snapshot criado hoje não prova que o mesmo dado estava disponível
em uma data histórica; essa diferença é explicada no
[protocolo temporal](protocolo_temporal.md).
Como os CSVs podem ser grandes, `data/snapshots/` está no `.gitignore` e deve
ser preservado separadamente quando fizer parte de um experimento publicado.

### Duplicatas

Duplicatas completamente idênticas geram um aviso, mas não bloqueiam o download. O arquivo bruto permanece inalterado e recebe o sufixo `_AVISO_DUPLICATAS`.

O manifesto registra:

- quantidade de linhas envolvidas;
- quantidade de chaves duplicadas;
- quantidade de cópias excedentes;
- flag `duplicate_rows`.

Se a mesma chave `DIA + SUBMERCADO` possuir valores diferentes, a validação continua sendo fatal, pois não existe uma escolha segura entre os registros conflitantes.

## Limitações conhecidas

- Na CCEE, `size` pode ser nulo e `hash` pode estar vazio. O hash local e, quando necessário, um novo download são usados como salvaguarda.
- Um portal pode anunciar `ETag` e ainda ignorar a requisição condicional. Isso aumenta o tráfego, mas não cria backup se o SHA-256 for idêntico.
- A seleção anual procura um ano de quatro dígitos no nome e na URL. Recursos sem ano são tratados como possivelmente acumulados e incluídos por segurança.
- A validação geral do ONS durante o download é principalmente estrutural. As
  regras semânticas de carga, EAR, ENA e balanço são aplicadas posteriormente por
  `src/clean.py`, mantendo separadas a aceitação do arquivo bruto e sua preparação
  para análise.
- A validação com Pandas carrega o CSV em memória, embora o download seja feito em streaming.
- Não existe remoção automática de backups nesta versão.

## Próxima etapa do fluxo

Depois que os CSVs estiverem em `data/raw/`, execute:

```powershell
pld transform
```

Esse comando não modifica os arquivos brutos. Ele cria os arquivos consolidados
em `data/interim/`. As transformações e verificações são detalhadas em
[Limpeza e transformação dos dados](limpeza_transformacao.md).
