# Coleta incremental de dados CKAN

Este documento descreve o componente responsável por coletar recursos CSV dos portais de dados abertos da CCEE e do ONS. O fluxo foi desenhado para que uma falha de rede, um CSV inválido ou um manifesto incompleto não destrua a última versão válida.

[Voltar ao README principal](../README.md)

## Como estudar a implementação

O fluxo original do coletor foi mantido de propósito. A melhor ordem de leitura é:

1. Abra `src/data/ccee.py`. Observe o laço que cria `CKANClient`, chama `get_resources()` e depois chama `download_resource()` para cada CSV.
2. Leia `get_resources()` em `src/data/ckan.py`. Ele faz uma requisição para `package_show`, valida o JSON e reutiliza a sessão HTTP.
3. Leia `download_resource()` aos poucos. O método está dividido por comentários: decisão de baixar, download temporário, comparação de hash, validação, backup e troca.
4. Por fim, abra `src/data/validate.py`. As validações foram deixadas fora do cliente porque o cliente CKAN não deve conhecer regras exclusivas do PLD.

As funções retornam dicionários simples. Por exemplo, um download retorna `{"status": "downloaded", "path": ..., "backup": ...}`. Isso evita uma hierarquia de classes e permite inspecionar os valores com facilidade durante o estudo ou pelo depurador.

## Instalação e comandos

Execute os comandos a partir da raiz do projeto:

```powershell
python -m pip install -r requirements.txt

# Todos os CSVs desde 2021 e recursos acumulados sem ano no nome ou URL
python -m src.update historical

# Recursos do ano atual e recursos acumulados
python -m src.update daily

# Ignora o cache e confirma novamente pelo conteúdo
python -m src.update daily --force

# Limita a execução a um portal
python -m src.update daily --portal ccee
python -m src.update historical --portal ons

# Testes sem dependência obrigatória dos portais externos
python -m pytest -q
```

O diretório de dados pode ser alterado com `--data-dir`. O primeiro ano da coleta histórica pode ser alterado com `--start-year`.

## Estrutura do coletor

```text
src/
├── data/
│   ├── ckan.py       # HTTP, manifesto, hash, download, backup e troca atômica
│   ├── ccee.py       # datasets e validação específica da CCEE
│   ├── ons.py        # datasets do ONS
│   └── validate.py   # validação geral e do PLD médio diário
└── update.py          # CLI, logs e status final

tests/                 # testes com sessões e respostas HTTP simuladas

data/
├── manifest.json
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
- A validação geral do ONS é estrutural. Regras semânticas próprias de cada dataset podem ser adicionadas em validadores separados.
- A validação com Pandas carrega o CSV em memória, embora o download seja feito em streaming.
- Não existe remoção automática de backups nesta versão.
