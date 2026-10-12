# Previsão do PLD Médio Diário

Este projeto reúne dados públicos do setor elétrico brasileiro para, futuramente,
desenvolver um modelo de previsão do **Preço de Liquidação das Diferenças (PLD)**
médio diário.

O trabalho está sendo construído em etapas. Atualmente, o projeto já realiza:

1. coleta incremental dos arquivos CSV da CCEE e do ONS;
2. validação e preservação dos dados brutos;
3. limpeza e padronização de cada dataset;
4. consolidação dos arquivos anuais em arquivos Parquet;
5. integração dos cinco datasets usando o PLD como histórico principal;
6. criação explícita da variável-alvo PLD D+1;
7. diagnóstico de disponibilidade temporal e risco de vazamento;
8. criação de features com lags de calendário, divisão cronológica e baseline;
9. testes de estrutura, qualidade e cobertura temporal.

O cenário preparado prevê D+1 às 00h de D. As variáveis verificadas do ONS usam
D-2 de forma conservadora e provisória. Antes de uma avaliação operacional,
ainda será necessário confirmar a disponibilidade ponto a ponto com snapshots
de publicação da CCEE e do ONS.

## Dados utilizados

| Fonte | Dataset | Arquivo consolidado | Granularidade |
| --- | --- | --- | --- |
| CCEE | PLD médio diário | `data/interim/pld.parquet` | diária por submercado |
| ONS | Carga de energia | `data/interim/carga_energia.parquet` | diária por submercado |
| ONS | Energia Armazenada (EAR) | `data/interim/ear.parquet` | diária por submercado |
| ONS | Energia Natural Afluente (ENA) | `data/interim/ena.parquet` | diária por submercado |
| ONS | Balanço de energia por subsistema | `data/interim/balanco_energia.parquet` | diária por submercado, calculada a partir dos registros horários |

Os arquivos originais permanecem em `data/raw/`. Eles não são sobrescritos pelas
etapas de limpeza. Os arquivos consolidados são gravados em `data/interim/`.
Os resultados da integração ficam em `data/processed/`. Essas três pastas de
dados não são versionadas pelo Git.

## Estrutura principal

```text
project_PLD/
├── data/
│   ├── raw/                    # CSVs originais baixados dos portais
│   ├── interim/                # Parquets limpos e consolidados
│   └── processed/              # histórico integrado e alvo D+1
├── docs/
│   ├── coleta_dados.md         # funcionamento do coletor CKAN
│   ├── limpeza_transformacao.md # limpeza e consolidação dos datasets
│   ├── integracao_dados.md      # merge e preparação inicial do alvo D+1
│   └── pre_modelagem.md         # disponibilidade, features e divisão temporal
├── src/
│   ├── data/
│   │   ├── ccee.py             # configuração da coleta da CCEE
│   │   ├── ckan.py             # cliente compartilhado para portais CKAN
│   │   ├── ons.py              # configuração da coleta do ONS
│   │   └── validate.py         # validações aplicadas durante o download
│   ├── clean.py                # limpeza individual de cada DataFrame
│   ├── features.py             # lags, calendário, baseline e divisão temporal
│   ├── merge.py                # integração e preparação do alvo D+1
│   ├── pipeline.py             # operações compartilhadas do pipeline
│   ├── transform.py            # configuração da consolidação de cada dataset
│   └── update.py               # ponto de entrada da coleta
├── tests/                      # testes de consolidação e comparação
└── requirements.txt
```

## Instalação

Com o Python instalado, crie e ative um ambiente virtual:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Instale as dependências:

```powershell
python -m pip install -r requirements.txt
```

## Fluxo de execução

### 1. Coletar os CSVs

Para baixar ou atualizar todo o histórico configurado:

```powershell
python -m src.update historical
```

Para a atualização diária:

```powershell
python -m src.update daily
```

O coletor compara o conteúdo remoto com o arquivo local. Quando não existe
alteração, o arquivo não é regravado. Quando existe alteração, a versão anterior
é preservada no histórico antes da substituição.

### 2. Limpar e consolidar os dados

Depois da coleta, execute:

```powershell
python src\transform.py
```

Esse script lê os CSVs anuais de `data/raw/`, aplica as funções de `src/clean.py`,
concatena os anos, verifica duplicatas e conflitos, ordena os registros e grava
os cinco arquivos Parquet em `data/interim/`.

### 3. Integrar os datasets e preparar o alvo D+1

```powershell
python src\merge.py
```

Esse comando cria dois arquivos:

- `data/processed/pld_integrado.parquet`: histórico integrado dos cinco
  datasets, mantendo todas as linhas do PLD;
- `data/processed/pld_treino.parquet`: mesmo histórico com `data_alvo` e
  `pld_d1`. Apesar do nome, ele ainda não está pronto para treinar modelos.

### 4. Preparar as features

```powershell
python -m src.features
```

Esse comando cria `data/processed/pld_features.parquet`, sem alterar os Parquets
intermediários, preencher valores ausentes ou remover linhas.

### 5. Executar os testes

```powershell
python -m pytest -q
```

Alguns testes também imprimem relatórios de diagnóstico. Para visualizá-los:

```powershell
python -m pytest -q -s
```

Os testes não corrigem os dados. Eles tornam inconsistências visíveis para que a
decisão de tratamento possa ser analisada e justificada.

## Documentação

- [Coleta incremental de dados CKAN](docs/coleta_dados.md): explica downloads,
  seleção de recursos, manifestos, backups e validações dos arquivos brutos.
- [Limpeza e transformação dos dados](docs/limpeza_transformacao.md): explica as
  funções de limpeza, a consolidação anual, as variáveis escolhidas, as unidades
  e os testes de qualidade.
- [Integração dos dados e alvo D+1](docs/integracao_dados.md): explica o merge,
  as ausências encontradas, a criação do alvo e o risco de vazamento temporal.
- [Pré-modelagem e disponibilidade temporal](docs/pre_modelagem.md): documenta
  o cenário das 00h, as incertezas de publicação, os lags, os `NaN`, a divisão
  cronológica e o baseline.

## Próximas etapas

- confirmar a disponibilidade histórica com snapshots de publicação;
- decidir o tratamento das linhas incompletas sem ocultar suas causas;
- congelar o período de teste e definir métricas de avaliação;
- treinar e avaliar os modelos de previsão do PLD.
