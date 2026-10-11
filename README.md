# Previsão do PLD Médio Diário

Este projeto reúne dados públicos do setor elétrico brasileiro para, futuramente,
desenvolver um modelo de previsão do **Preço de Liquidação das Diferenças (PLD)**
médio diário.

O trabalho está sendo construído em etapas. Atualmente, o projeto já realiza:

1. coleta incremental dos arquivos CSV da CCEE e do ONS;
2. validação e preservação dos dados brutos;
3. limpeza e padronização de cada dataset;
4. consolidação dos arquivos anuais em arquivos Parquet;
5. testes de estrutura, qualidade e cobertura temporal.

A integração definitiva dos datasets e o treinamento do modelo ainda não foram
finalizados.

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
Essas duas pastas de dados não são versionadas pelo Git.

## Estrutura principal

```text
project_PLD/
├── data/
│   ├── raw/                    # CSVs originais baixados dos portais
│   └── interim/                # Parquets limpos e consolidados
├── docs/
│   ├── coleta_dados.md         # funcionamento do coletor CKAN
│   └── limpeza_transformacao.md # limpeza e consolidação dos datasets
├── src/
│   ├── data/
│   │   ├── ccee.py             # configuração da coleta da CCEE
│   │   ├── ckan.py             # cliente compartilhado para portais CKAN
│   │   ├── ons.py              # configuração da coleta do ONS
│   │   └── validate.py         # validações aplicadas durante o download
│   ├── clean.py                # limpeza individual de cada DataFrame
│   ├── transform.py            # consolidação anual e exportação em Parquet
│   ├── merge.py                # integração em desenvolvimento
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

### 3. Executar os testes

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

## Próximas etapas

- finalizar a integração dos datasets por data e submercado;
- definir defasagens que evitem vazamento temporal na previsão D+1;
- construir as features do modelo;
- treinar e avaliar os modelos de previsão do PLD.
