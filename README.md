# Sistema de previsão do PLD

Este projeto reúne dados públicos da [Câmara de Comercialização de Energia Elétrica (CCEE)](https://www.ccee.org.br/precos/conceitos-precos) e do [Operador Nacional do Sistema Elétrico (ONS)](https://www.ons.org.br/) para investigar a previsão multi-horizonte do [PLD horário](https://dadosabertos.ccee.org.br/dataset/pld_horario) nos quatro submercados do Sistema Interligado Nacional (Sudeste/Centro-Oeste, Sul, Nordeste e Norte) a partir de variáveis operativas e hidrológicas.

A pesquisa estrutura-se em duas frentes experimentais sobre a mesma base de dados e features:

- **Frente principal — Transferência de aprendizado entre submercados (Opção B):** avalia se o conhecimento aprendido em um ou mais submercados melhora a previsão multi-horizonte do PLD horário em outro submercado-alvo (comparando modelos independentes por região, modelos conjuntos multi-submercado e arquiteturas com _transfer learning_ na linha de [Gunduz et al., 2023](https://arxiv.org/abs/2007.03762)). O foco inclui identificar em quais condições operativas ocorre ganho de generalização (como em regimes com poucos dados históricos) e quando surge transferência negativa (como nos episódios de desacoplamento de preços por saturação dos limites de intercâmbio).
- **Frente de validação — Adaptação sob mudanças de distribuição (Opção A):** valida a estabilidade temporal dos modelos diante de mudanças de regime no PLD (complementando diagnósticos econométricos como o de [de Castro Matias e Tabak, 2025](https://ideas.repec.org/p/hal/journl/hal-05562231.html)), comparando treinamento estático, atualização periódica e retreinamento acionado por detectores de _concept drift_ quanto à recuperação de desempenho por horizonte e ao custo computacional.

O fluxo horário multi-horizonte é o caminho principal do sistema; a pipeline diária D+1 ([PLD médio diário](https://dadosabertos.ccee.org.br/dataset/pld_media_diaria)) continua disponível para compatibilidade.

O trabalho está sendo construído em etapas. Atualmente, o projeto já realiza:

1. coleta incremental dos arquivos CSV da [CCEE](https://dadosabertos.ccee.org.br/dataset/pld_horario) e do [ONS](https://www.ons.org.br/);
2. validação e preservação dos dados brutos;
3. limpeza e padronização de cada dataset nos quatro submercados;
4. consolidação dos arquivos anuais em arquivos Parquet;
5. integração horária de PLD, carga, geração, EAR e ENA;
6. criação explícita dos 24 alvos H+12 a H+35 por dia e submercado;
7. diagnóstico de disponibilidade temporal e risco de vazamento;
8. criação de features horárias e hidrológicas sem preenchimento silencioso;
9. testes de estrutura, qualidade e cobertura temporal;
10. coleta prospectiva automática duas vezes ao dia, com snapshots, logs e auditoria de execuções ausentes.

A camada de dados e features horárias está implementada e já organiza os quatro submercados de forma padronizada e sincronizada no tempo. O treinamento e a avaliação comparativa dos modelos (independentes, conjuntos, com transferência de aprendizado e sob políticas de atualização adaptativa) serão desenvolvidos nas etapas seguintes.

No fluxo diário legado, o cenário prevê D+1 às 00h de D. No fluxo horário principal, emite às 12h de D-1 para as 24 horas de D. As variáveis verificadas do ONS usam uma defasagem configurável, por padrão dois dias antes da data de emissão, de forma conservadora e provisória. Antes de uma avaliação operacional, ainda será necessário confirmar a disponibilidade ponto a ponto com snapshots de publicação da CCEE e do ONS.

## Dados utilizados

| Fonte                                                             | Dataset                           | Arquivo consolidado                            | Granularidade                                                    |
| ----------------------------------------------------------------- | --------------------------------- | ---------------------------------------------- | ---------------------------------------------------------------- |
| [CCEE](https://dadosabertos.ccee.org.br/dataset/pld_media_diaria) | PLD médio diário                  | `data/interim/pld.parquet`                     | diária por submercado                                            |
| [CCEE](https://dadosabertos.ccee.org.br/dataset/pld_horario)      | PLD horário                       | `data/interim/pld_horario.parquet`             | horária por submercado                                           |
| [ONS](https://www.ons.org.br/)                                    | Carga de energia legada           | `data/interim/carga_energia.parquet`           | diária por submercado                                            |
| [ONS](https://www.ons.org.br/)                                    | Energia Armazenada (EAR)          | `data/interim/ear.parquet`                     | diária por submercado                                            |
| [ONS](https://www.ons.org.br/)                                    | Energia Natural Afluente (ENA)    | `data/interim/ena.parquet`                     | diária por submercado                                            |
| [ONS](https://www.ons.org.br/)                                    | Balanço de energia por subsistema | `data/interim/balanco_energia.parquet`         | diária por submercado, calculada a partir dos registros horários |
| [ONS](https://www.ons.org.br/)                                    | Balanço diário (nome novo)        | `data/interim/balanco_energia_diario.parquet`  | diária por submercado; o nome antigo acima segue disponível      |
| [ONS](https://www.ons.org.br/)                                    | Balanço horário principal         | `data/interim/balanco_energia_horario.parquet` | carga, geração e intercâmbio horários por submercado             |

Os arquivos originais permanecem em `data/raw/`. Um `pld collect --snapshot`
também registra cópias imutáveis e metadados em `data/snapshots/`. As etapas de
limpeza não alteram o bruto. Os consolidados ficam em `data/interim/` e as
integrações, alvos e features em `data/processed/`. Essas pastas não são versionadas.

## Estrutura principal

```text
project_PLD/
├── data/
│   ├── raw/                    # CSVs atuais e backups
│   ├── snapshots/              # cópias capturadas com horário e SHA-256
│   ├── interim/                # Parquets diários e horários por fonte
│   └── processed/              # integração, alvos e features diárias/horárias
├── docs/
│   ├── coleta_dados.md         # funcionamento do coletor CKAN
│   ├── automacao_coleta.md     # Agendador do Windows, logs e auditoria
│   ├── limpeza_transformacao.md # limpeza e consolidação dos datasets
│   ├── integracao_dados.md      # merge e preparação inicial do alvo D+1
│   └── pre_modelagem.md         # disponibilidade, features e divisão temporal
├── src/
│   ├── pld_forecast/
│   │   ├── collectors/         # CKAN, CCEE, ONS, validação e snapshots
│   │   ├── data/               # disponibilidade, limpeza e consolidação
│   │   ├── features/           # features diárias e horárias
│   │   ├── config.py           # corte temporal e horizontes
│   │   └── cli.py              # comando pld
│   ├── data/ e módulos antigos # caminhos de compatibilidade
│   └── update.py               # comando de coleta antigo
├── tests/                      # testes de consolidação e comparação
├── scripts/                    # execução e gestão das tarefas do Windows
└── pyproject.toml              # instalação e comando pld
```

## Instalação

Com o Python instalado, crie e ative um ambiente virtual:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Instale o pacote e as dependências de desenvolvimento:

```powershell
python -m pip install -e ".[dev]"
```

## Fluxo de execução

### 1. Coletar os CSVs

Para baixar ou atualizar todo o histórico configurado:

```powershell
pld collect historical --snapshot
```

Para a atualização diária:

```powershell
pld collect daily --snapshot
```

Para instalar a coleta prospectiva automática às 11:45 e 20:30 no Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_scheduled_tasks.ps1
```

Consulte `docs/automacao_coleta.md` antes de
instalar: o documento explica o fuso, o instante real de captura, logs, lock,
retentativas, auditoria de horários perdidos, backup e gestão das tarefas.

O coletor compara o conteúdo remoto com o arquivo local. Quando não existe
alteração, o arquivo não é regravado. Quando existe alteração, a versão anterior
é preservada no histórico antes da substituição.

### 2. Limpar e consolidar os dados

Depois da coleta, execute:

```powershell
pld transform
```

Esse script lê os CSVs anuais de `data/raw/`, aplica as funções de `src/clean.py`,
concatena os anos, verifica duplicatas e conflitos, ordena os registros e grava
os cinco Parquets diários e o balanço horário em `data/interim/`. O Parquet de
PLD horário é criado quando seus CSVs estão disponíveis localmente.

### 3. Integrar os datasets e preparar os alvos horários

```powershell
pld integrate
```

O fluxo diário continua criando dois arquivos:

- `data/processed/pld_integrado.parquet`: histórico integrado dos cinco
  datasets, mantendo todas as linhas do PLD;
- `data/processed/pld_treino.parquet`: mesmo histórico com `data_alvo` e
  `pld_d1`. Apesar do nome, ele ainda não está pronto para treinar modelos.

Se `pld_horario.parquet` estiver disponível, o mesmo comando cria
`pld_horario_integrado.parquet` e `pld_horario_alvos.parquet`. Por padrão,
cada emissão às 12h de D-1 tem 24 alvos de D (H+12 a H+35). Para incluir D+2
e D+3, use `pld integrate --days-ahead 3`. A opção
`--first-target-day-offset 0 --issue-hour 0` permite emitir às 00h do próprio
dia-alvo. Horas não publicadas ficam `NaN`.

### 4. Preparar as features

```powershell
pld features
```

Esse comando cria `data/processed/pld_features.parquet` e, quando existem alvos
horários, `pld_horario_features.parquet` e
`pld_horario_features_diagnostico.parquet`. Não altera os Parquets intermediários,
preenche ausências nem remove linhas. `--ons-lag-days 2` é a hipótese histórica
conservadora padrão. No fluxo principal, carga e geração vêm do balanço horário;
EAR e ENA continuam diárias. A carga diária não é duplicada nas features.

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

Os comandos antigos (`python -m src.update`, `python -m src.transform`,
`python -m src.merge`, `python -m src.features`) continuam disponíveis. Nesta
etapa, `pld integrate` e `pld features` executam também o fluxo horário quando
existem CSVs horários da CCEE;
`pld backtest`, `pld forecast` e `pld evaluate` informam que ainda não foram
implementados.

## Documentação

- `docs/coleta_dados.md`: explica downloads,
  seleção de recursos, manifestos, backups e validações dos arquivos brutos.
- `docs/automacao_coleta.md`: explica como
  instalar, verificar, pausar e remover as tarefas diárias do Windows.
- `docs/limpeza_transformacao.md`: explica as
  funções de limpeza, a consolidação anual, as variáveis escolhidas, as unidades
  e os testes de qualidade.
- `docs/integracao_dados.md`: explica os
  merges, a grade multi-horizonte e a preservação do fluxo diário.
- `docs/pre_modelagem.md`: documenta
  o cenário horário, as features, os `NaN`, a divisão cronológica e as limitações.
- `docs/protocolo_temporal.md`: explica o novo
  cenário horário, os cinco tempos e as regras contra vazamento.

## Próximas etapas

- acumular snapshots prospectivos para comprovar disponibilidade real;
- decidir o tratamento das linhas incompletas sem ocultar suas causas;
- congelar o período de teste e definir métricas de avaliação por submercado e horizonte;
- treinar e comparar modelos independentes, conjuntos e com _transfer learning_ entre os quatro submercados (Opção B);
- validar a estabilidade dos modelos frente a mudanças de regime com políticas de retreinamento estático, periódico e adaptativo (Opção A).
