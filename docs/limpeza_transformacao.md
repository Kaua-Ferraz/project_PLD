# Limpeza e transformação dos dados

Este documento explica como os CSVs brutos são validados, padronizados e
consolidados em arquivos Parquet. A implementação fica em
`src/pld_forecast/data/clean.py` e `src/pld_forecast/data/transform.py`;
`src/clean.py` e `src/transform.py` continuam como caminhos de compatibilidade.
A integração é uma etapa posterior e já está implementada em `data/integration.py`.

O novo fluxo também preserva o balanço horário em
`data/interim/balanco_energia_horario.parquet` e consolida o PLD horário em
`data/interim/pld_horario.parquet` quando houver CSVs dessa fonte.

[Voltar ao README principal](../README.md) ·
[Ver a documentação da coleta](coleta_dados.md)

## Visão geral do fluxo

```text
CSV anual em data/raw/
        ↓
função clean_* em clean.py
        ↓
DataFrame limpo daquele arquivo
        ↓
função read_* em transform.py
        ↓
concatenação dos anos + verificação de conflitos
        ↓
Parquet consolidado em data/interim/
```

Essa separação deixa cada função com uma responsabilidade simples:

- `clean.py` recebe um `DataFrame`, valida seus valores e devolve outro
  `DataFrame` com nomes e tipos padronizados;
- `pipeline.py` contém as operações genéricas repetidas pelo fluxo;
- `transform.py` informa a pasta, a função de limpeza, as chaves, as colunas e o
  destino de cada dataset;
- `process_csv_dataset()` encontra os CSVs anuais, chama a limpeza de cada
  arquivo, concatena os resultados, verifica sobreposições e exporta o conjunto.

Os CSVs de `data/raw/` nunca são alterados por essas funções. Quando um valor é
suspeito, o código gera um erro ou um aviso; ele não preenche, converte para zero,
usa `abs()` nem remove o registro silenciosamente.

## Como executar

Primeiro, faça a coleta conforme explicado em `coleta_dados.md`. Depois, a partir
da raiz do projeto, execute:

```powershell
pld transform
```

O bloco final de `transform.py` chama, nesta ordem:

```python
read_pld()
read_carga()
read_ear()
read_ena()
read_balanco()
read_balanco_horario()
read_pld_horario()  # quando existem CSVs locais
```

Se um arquivo falhar, a mensagem informa qual CSV estava sendo processado e
preserva a exceção original como causa. Assim, fica mais fácil descobrir se o
problema está na leitura, nas colunas ou nos dados.

## Operações comuns de limpeza

As funções de limpeza começam com uma cópia:

```python
df = dataframe.copy()
```

Isso evita alterar por efeito colateral o `DataFrame` recebido. Em seguida, elas
seguem uma sequência parecida:

1. verificam se todas as colunas obrigatórias existem;
2. rejeitam arquivos vazios;
3. renomeiam as colunas para nomes claros e consistentes;
4. removem espaços desnecessários dos textos e padronizam os submercados;
5. convertem datas com `pd.to_datetime(..., errors="raise")`;
6. convertem medidas com `pd.to_numeric(..., errors="raise")`;
7. verificam valores nulos e regras físicas básicas;
8. procuram duplicatas e conflitos na chave `data + submercado`;
9. selecionam somente as colunas finais.

O argumento `errors="raise"` é intencional: uma data ou um número inválido
interrompe a execução e fica visível, em vez de virar `NaT` ou `NaN` sem que se
perceba.

## Funções compartilhadas do pipeline

As repetições estruturais foram separadas em `src/pipeline.py`. Elas não possuem
regras específicas de PLD, carga, EAR, ENA ou balanço.

| Função | Responsabilidade |
| --- | --- |
| `validate_input_dataframe()` | verifica arquivo vazio e colunas obrigatórias |
| `validate_no_missing_values()` | verifica nulos nas colunas informadas |
| `validate_unique_keys()` | garante uma linha por combinação de chaves |
| `remove_identical_duplicates()` | remove cópias iguais e rejeita conflitos |
| `sort_dataframe()` | ordena pelas chaves e recria o índice |
| `save_parquet()` | cria a pasta e salva sem incluir o índice |
| `process_csv_dataset()` | executa leitura, limpeza, concatenação e exportação |

Por exemplo, `clean_ear()` continua responsável por saber que a EAR verificada
não pode superar a EAR máxima. A função genérica sabe apenas verificar estrutura,
nulos e duplicatas conforme as colunas recebidas.

Essa divisão é usada tanto nas séries diárias quanto nas horárias. PLD e balanço
usam a chave `instante + submercado`; carga diária, EAR e ENA usam
`data + submercado`. As regras horárias já estão implementadas e não dependem da
posição das linhas no CSV.

## PLD médio diário

Funções: `clean_pld()` e `read_pld()`.

| Coluna final | Significado |
| --- | --- |
| `data` | dia de referência |
| `submercado` | NORTE, NORDESTE, SUDESTE ou SUL |
| `pld_medio_dia` | preço médio diário publicado pela CCEE |

As colunas originais `DIA`, `SUBMERCADO` e `PLD_MEDIA_DIA` são renomeadas. A
data, originalmente escrita como dia/mês/ano, é convertida para o tipo de data do
Pandas. O preço deve ser numérico, não nulo e não negativo.

Em 2023 existem chaves repetidas no arquivo publicado. O código primeiro verifica
se os preços dessas repetições são iguais. Somente duplicatas idênticas são
consolidadas; preços diferentes para a mesma data e o mesmo submercado geram erro.
O CSV bruto com o aviso continua preservado.

O arquivo final é `data/interim/pld.parquet`.

## Carga de energia

Funções: `clean_carga()` e `read_carga()`.

| Coluna final | Unidade | Significado |
| --- | --- | --- |
| `data` | — | dia de referência |
| `submercado` | — | região elétrica padronizada |
| `carga_mwmed` | MW médios | demanda média de energia no dia |

Além de padronizar data e região, a limpeza confirma a correspondência entre o
código e o nome do subsistema. A carga deve ser numérica, não nula e maior que
zero. Duplicatas só são removidas depois da verificação de conflitos.

O arquivo final é `data/interim/carga_energia.parquet`.

## Energia Armazenada (EAR)

Funções: `clean_ear()` e `read_ear()`.

A EAR representa a energia que poderia ser produzida usando a água armazenada
nos reservatórios, considerando as condições do sistema hidrelétrico. Ela ajuda a
indicar a disponibilidade de recurso hídrico: níveis menores podem aumentar a
necessidade de geração mais cara e influenciar o PLD.

| Coluna final | Unidade | Significado |
| --- | --- | --- |
| `ear_max_mwmes` | MWmês | capacidade máxima de armazenamento energético |
| `ear_mwmes` | MWmês | energia armazenada verificada |
| `ear_percentual` | % | parcela ocupada da capacidade máxima |

As medidas absoluta e percentual são mantidas porque não são equivalentes para o
modelo. `ear_mwmes` informa a quantidade de energia disponível; o percentual
informa o nível relativo à capacidade do subsistema. Dois subsistemas podem ter o
mesmo percentual e volumes absolutos muito diferentes.

A limpeza verifica, entre outras regras:

- capacidade máxima e EAR verificada maiores que zero;
- EAR verificada não superior à capacidade máxima;
- percentual no intervalo de 0 a 100;
- coerência entre `ear_percentual` e `ear_mwmes / ear_max_mwmes * 100`, aceitando
  uma pequena diferença de arredondamento de 0,01 ponto percentual.

O arquivo final é `data/interim/ear.parquet`.

## Energia Natural Afluente (ENA)

Funções: `clean_ena()` e `read_ena()`.

A ENA expressa o potencial de geração associado às vazões naturais que chegam aos
aproveitamentos hidrelétricos. Ela é importante para o PLD porque ajuda a mostrar
se está entrando mais ou menos recurso hídrico no sistema.

| Coluna final | Unidade | Significado |
| --- | --- | --- |
| `ena_bruta_mwmed` | MW médios | potencial total associado às afluências |
| `ena_bruta_percentual_mlt` | % da MLT | ENA bruta comparada à Média de Longo Termo |
| `ena_armazenavel_mwmed` | MW médios | parcela da ENA que pode ser armazenada |
| `ena_armazenavel_percentual_mlt` | % da MLT | parcela armazenável comparada à MLT |

Os valores em MW médios mostram a magnitude absoluta. Os percentuais da MLT dão
contexto hidrológico: 100% representa a referência histórica da época, abaixo de
100% indica condição inferior à média e acima de 100% indica condição superior.
Por isso, percentuais da MLT podem ultrapassar 100 e não são tratados como erro.

O código mantém as quatro medidas. Ele verifica valores numéricos, nulos,
negativos e se a parcela armazenável não supera a bruta. Nessa última comparação,
uma tolerância de `1e-6` serve apenas para evitar falsos conflitos causados pela
representação de números decimais no computador; ela não é uma tolerância de
qualidade dos dados.

O arquivo final é `data/interim/ena.parquet`.

## Balanço de energia por subsistema

Funções: `clean_balanco()` e `read_balanco()`.

Esse dataset é diferente dos anteriores porque chega com um registro por hora. A
limpeza valida os dados horários antes de calcular as médias diárias.

| Coluna final | Unidade | Significado |
| --- | --- | --- |
| `geracao_hidraulica_mwmed` | MW médios | geração hidráulica média do dia |
| `geracao_termica_mwmed` | MW médios | geração térmica média do dia |
| `geracao_eolica_mwmed` | MW médios | geração eólica média do dia |
| `geracao_solar_mwmed` | MW médios | geração solar média do dia |
| `carga_balanco_mwmed` | MW médios | carga média calculada a partir das horas |
| `intercambio_mwmed` | MW médios | intercâmbio líquido médio, com sinal preservado |

Antes da agregação, o código confirma:

- a correspondência entre código e nome do subsistema;
- a inexistência de duplicatas em `instante + submercado`;
- a presença dos quatro submercados;
- a existência de exatamente 24 registros em cada dia e submercado;
- a sequência exata das horas de `00:00` a `23:00`;
- a inexistência de dias inteiros ausentes para cada submercado;
- a inexistência de valores nulos;
- carga não negativa.

O registro `SIN` é validado, mas retirado antes da agregação porque é o total do
Sistema Interligado Nacional, e não um quinto submercado. Depois disso, a média é
calculada com:

```python
df.groupby(["data", "submercado"], as_index=False)[colunas_numericas].mean()
```

O `groupby()` forma um grupo para cada combinação de data e submercado. O
`.mean()` calcula a média das 24 observações daquele grupo. Essa média só é feita
depois que as 24 horas foram confirmadas; caso contrário, uma média de um dia
incompleto poderia parecer válida.

O intercâmbio pode ser positivo ou negativo. Seu sinal representa o sentido
definido pela convenção operacional do ONS, portanto é preservado. O código não
usa `abs()` e não exige que a soma dos quatro submercados seja zero. A interpretação
de positivo como importação ou exportação deve esperar a confirmação da convenção
na documentação da fonte.

Valores negativos de geração geram um aviso e são preservados para investigação,
em vez de serem corrigidos automaticamente. Isso é importante porque até um valor
muito pequeno pode ser um dado publicado, um efeito de medição ou uma anomalia que
merece análise separada.

O arquivo final é `data/interim/balanco_energia.parquet`.

## Como a consolidação entre anos funciona

Cada `read_*()` chama `process_csv_dataset()` informando somente o que muda. Por
exemplo, a configuração da carga informa:

```python
return process_csv_dataset(
    source_directory=pasta_da_carga,
    destination=INTERIM_DIRECTORY / "carga_energia.parquet",
    dataset_name="carga",
    clean_function=clean_carga,
    keys=["data", "submercado"],
    value_columns=["carga_mwmed"],
    final_columns=["data", "submercado", "carga_mwmed"],
)
```

Internamente, a função compartilhada guarda os DataFrames anuais em uma lista e
os reúne assim:

```python
df_consolidado = pd.concat(dataframes, ignore_index=True)
```

O `concat()` empilha as linhas. `ignore_index=True` cria um índice novo e contínuo,
pois os índices antigos de cada CSV não possuem significado depois da união.

Em seguida, o código procura chaves repetidas e conta quantos valores diferentes
existem em cada chave. Um exemplo simplificado é:

```python
conflitos = (
    df.groupby(["data", "submercado"])["carga_mwmed"]
    .nunique()
)
```

Se `nunique()` retornar mais de um, há valores conflitantes para a mesma chave e
a execução para. Se os valores forem idênticos, a cópia repetida pode ser removida
com segurança. Por fim, os registros são organizados:

```python
df = (
    df.sort_values(["data", "submercado"])
    .reset_index(drop=True)
)
```

Ordenar torna o arquivo previsível para inspeção. `reset_index(drop=True)` recria
o índice depois da ordenação e descarta o índice antigo.

## Arquivos gerados

| Função | Origem em `data/raw/` | Saída em `data/interim/` |
| --- | --- | --- |
| `read_pld()` | `ccee/pld_media_diaria/current/` | `pld.parquet` |
| `read_carga()` | `ons/carga-energia/current/` | `carga_energia.parquet` |
| `read_ear()` | `ons/ear-diario-por-subsistema/current/` | `ear.parquet` |
| `read_ena()` | `ons/ena-diario-por-subsistema/current/` | `ena.parquet` |
| `read_balanco()` | `ons/balanco-energia-subsistema/current/` | `balanco_energia.parquet` |
| `read_balanco()` | mesma origem | `balanco_energia_diario.parquet` (e nome antigo compatível) |
| `read_balanco_horario()` | mesma origem | `balanco_energia_horario.parquet` |
| `read_pld_horario()` | `ccee/pld_horario/current/` | `pld_horario.parquet` |

O PLD horário fica em `instante`, `data`, `hora`, `submercado` e
`pld_horario` (R$/MWh). A chave é `instante + submercado`; a hora vai de 0 a 23.
O balanço horário mantém as seis medidas em MWmed, inclusive o sinal original
do intercâmbio. A média diária é guardada separadamente e não substitui as
observações horárias.

O formato Parquet preserva tipos de dados, como datas e números, e costuma ser
mais compacto e rápido para análise que o CSV.

## Testes de consolidação

Execute todos os testes com:

```powershell
python -m pytest -q
```

Para também ver contagens e relatórios impressos:

```powershell
python -m pytest -q -s
```

Os testes de consolidação verificam, conforme o dataset:

- nomes e tipos das colunas;
- quantidade de linhas e período coberto;
- registros por ano e por submercado;
- duplicatas e conflitos;
- valores nulos, negativos ou fisicamente incompatíveis;
- datas ausentes no conjunto e em cada submercado;
- cobertura horária completa no balanço antes da média diária.

Também existe um teste comparativo entre `carga_energia.parquet` e a carga obtida
do balanço. Ele usa dois tipos de `merge()`:

```python
# Mantém todas as chaves e revela registros exclusivos de cada fonte.
comparacao_externa = carga.merge(
    balanco,
    on=["data", "submercado"],
    how="outer",
    indicator=True,
    validate="one_to_one",
)

# Mantém somente as chaves presentes nas duas fontes para comparar valores.
comparacao = carga.merge(
    balanco,
    on=["data", "submercado"],
    how="inner",
    validate="one_to_one",
)
```

`indicator=True` cria a coluna `_merge`, que mostra se a chave veio da esquerda,
da direita ou das duas fontes. `validate="one_to_one"` confirma que cada lado tem
no máximo um registro por data e submercado.

O teste calcula a diferença assinada, a diferença absoluta e a diferença
percentual, além de mostrar as maiores divergências. Ele não usa uma tolerância
arbitrária e não falha só porque existem diferenças: seu objetivo é produzir um
diagnóstico. Se as duas cargas forem numericamente equivalentes, provavelmente
não faz sentido usá-las simultaneamente como features do modelo, pois carregariam
a mesma informação. Essa decisão deve ser tomada apenas depois de analisar o
relatório e a disponibilidade temporal de cada fonte.

## Próxima etapa do fluxo

A integração dos cinco datasets e a criação explícita do alvo PLD D+1 são
explicadas em [Integração dos dados e preparação do PLD D+1](integracao_dados.md).

A criação de features e o treinamento do modelo ainda não foram implementados.
Antes dessas etapas, será necessário confirmar quando cada variável se torna
disponível e aplicar defasagens adequadas. Usar no modelo uma informação que só é
publicada depois do instante da previsão causaria vazamento temporal.

