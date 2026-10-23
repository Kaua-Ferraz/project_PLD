# Integração horária multi-horizonte e fluxo diário legado

## Etapa horária multi-horizonte

Este é o caminho principal da pesquisa. O fluxo diário descrito no apêndice
continua disponível apenas para compatibilidade. Com os CSVs da CCEE,
`pld integrate` chama `integrate_hourly_datasets()` e
`prepare_multi_horizon_targets()`.

`integrate_hourly_datasets()` começa com uma cópia do PLD horário. O balanço,
incluindo sua carga horária, entra por `instante + submercado` (`one_to_one`);
EAR e ENA entram por `data + submercado` (`many_to_one`, porque as 24 horas do
dia compartilham o indicador diário). A carga diária só é aceita quando passada
explicitamente à função para reproduzir uma análise legada; o comando normal
não a inclui no dataset horário.
Antes de cada junção, um `outer merge` com `_merge` conta `left_only` e
`right_only`. A junção final é sempre `left`, para nenhuma observação de PLD
desaparecer e nenhuma data exclusiva do ONS virar alvo. As colunas ONS do
mesmo instante são diagnósticas, não features disponíveis para prever esse
instante.

O resultado é `data/processed/pld_horario_integrado.parquet`. Em separado,
`prepare_multi_horizon_targets()` constrói uma grade com emissão, hora-alvo e
quatro submercados. Para 12h de D-1, o `horizon` vai de 12 a 35. Um `merge`
por `target_time + submercado` consulta o PLD oficial; se a hora não existe,
`target_pld` fica nulo, sem deslocar a série por `shift()`. O arquivo é
`data/processed/pld_horario_alvos.parquet`. `--days-ahead 3` inclui D+2 e
D+3 (até H+83). Datas futuras além do fim publicado também ficam nulas.

Exemplo: uma emissão em 09/01 às 12h para 10/01 às 00h tem horizonte 12;
para 10/01 às 23h, horizonte 35. Isso difere de contar linhas em sequência:
uma hora faltante não altera a chave da próxima.

O integrado contém valores contemporâneos do ONS para diagnóstico e análise
exploratória. Ele não é entregue diretamente ao modelo: as features são
reconsultadas com as regras temporais descritas em `protocolo_temporal.md`.

[Voltar ao README principal](../README.md) ·
[Ver a limpeza e transformação](limpeza_transformacao.md) ·
[Ver a pré-modelagem](pre_modelagem.md)

Entradas principais em `data/interim/`:

| Arquivo | Frequência | Uso |
| --- | --- | --- |
| `pld_horario.parquet` | horária | âncora e variável-alvo |
| `balanco_energia_horario.parquet` | horária | carga, gerações e intercâmbio |
| `ear.parquet` | diária | EAR máxima, absoluta e percentual |
| `ena.parquet` | diária | ENA bruta/armazenável absoluta e % MLT |

Saídas principais:

| Arquivo | Conteúdo |
| --- | --- |
| `pld_horario_integrado.parquet` | histórico contemporâneo para diagnóstico |
| `pld_horario_alvos.parquet` | grade longa `issue_time`, `target_time`, `horizon`, `submercado`, `target_pld` |

```powershell
pld integrate
```

O cenário padrão emite às 12h de D-1 e gera exatamente 24 alvos por dia e
submercado, de H+12 a H+35. Horas sem PLD oficial permanecem nulas.

## Apêndice: integração diária legada

As seções abaixo documentam `merge_datasets()` e `prepare_pld_d1()`. Elas são
mantidas para reprodutibilidade, mas não definem mais o objetivo principal.

### Arquivos de entrada e saída

Entradas, todas em `data/interim/`:

| Arquivo | Principais informações |
| --- | --- |
| `pld.parquet` | `pld_medio_dia`, que é a variável que queremos prever |
| `carga_energia.parquet` | `carga_mwmed` |
| `ear.parquet` | EAR máxima, absoluta e percentual |
| `ena.parquet` | ENA bruta e armazenável, em MW médios e % da MLT |
| `balanco_energia.parquet` | gerações, carga do balanço e intercâmbio |

Saídas, em `data/processed/`:

| Arquivo | Finalidade |
| --- | --- |
| `pld_integrado.parquet` | histórico integrado, preservando as linhas do PLD |
| `pld_treino.parquet` | histórico com `data_alvo` e `pld_d1`; ainda não está pronto para treinamento |

Nenhum arquivo bruto ou consolidado é modificado. Os dois arquivos processados
podem ser reconstruídos executando novamente o script.

## Como executar

Depois de gerar os cinco Parquets consolidados com `src/transform.py`, execute:

```powershell
python src\merge.py
```

O script chama duas funções:

```python
dados_integrados = merge_datasets()
prepare_pld_d1(dados_integrados)
```

`merge_datasets()` cria o histórico integrado. `prepare_pld_d1()` recebe esse
histórico e cria o alvo do próximo dia em uma etapa separada.

## Verificações feitas antes do merge

Para cada DataFrame, o código verifica:

- se o dataset não está vazio;
- se `data` e `submercado` existem;
- se as chaves não possuem valores nulos;
- se não há mais de uma linha para a mesma data e o mesmo submercado;
- se `data` possui tipo de data e não contém horários;
- se `submercado` possui tipo textual;
- se não existem nomes de colunas duplicados.

Na leitura atual, o PLD pode retornar `submercado` com o tipo textual `string`,
enquanto outros Parquets podem retornar `str`. Os dois são tipos de texto. O
código valida essa compatibilidade e converte as cópias locais para `string`
antes da junção:

```python
dataframe = dataframe.copy()
dataframe["submercado"] = dataframe["submercado"].astype("string")
```

Isso não modifica os Parquets de origem. A conversão apenas torna a chave
uniforme no processo de integração.

O código também compara os nomes das colunas não usadas como chave. Se duas
fontes possuírem uma coluna com o mesmo nome, o processo para antes do merge. Isso
evita que o Pandas crie silenciosamente nomes como `valor_x` e `valor_y`.

A carga específica e a carga do balanço já possuem nomes diferentes:
`carga_mwmed` e `carga_balanco_mwmed`. Portanto, ambas podem ser preservadas para
análise sem ambiguidade.

## Por que o PLD é a tabela principal

O objetivo futuro é prever o PLD. Cada exemplo do modelo deverá corresponder a
uma observação de PLD em determinada data e submercado. Por isso, o DataFrame do
PLD é copiado primeiro:

```python
df_final = df_pld.copy()
```

As fontes do ONS são acrescentadas uma por vez. Essa escolha significa que:

- nenhuma observação existente de PLD deve desaparecer;
- uma data existente apenas no ONS não cria uma nova observação-alvo;
- a falta de correspondência no ONS aparece como valor nulo e pode ser analisada.

## Como funciona o `merge()`

O trecho principal é:

```python
df_final = df_final.merge(
    dataframe,
    on=["data", "submercado"],
    how="left",
    validate="one_to_one",
)
```

### `on`

`on=["data", "submercado"]` informa quais colunas identificam a mesma
observação nas duas tabelas. Não seria suficiente usar somente a data, pois cada
dia possui quatro submercados.

Exemplo:

```text
2026-10-10 + NORTE
2026-10-10 + NORDESTE
```

São duas chaves diferentes, mesmo tendo a mesma data.

### `how="left"`

A junção à esquerda mantém todas as linhas do DataFrame localizado à esquerda,
que neste caso é o PLD. Quando a fonte da direita não possui a mesma chave, suas
colunas ficam nulas.

Os principais tipos de junção são:

| Tipo | Linhas preservadas |
| --- | --- |
| `left` | todas da esquerda e as correspondências da direita |
| `right` | todas da direita e as correspondências da esquerda |
| `inner` | somente chaves presentes nos dois lados |
| `outer` | todas as chaves dos dois lados |

O `inner` descartaria dias de PLD sem dados do ONS. O `outer` acrescentaria datas
sem PLD. Nenhum desses comportamentos corresponde ao objetivo desta etapa.

### `validate="one_to_one"`

Essa opção exige no máximo uma linha de cada lado para a mesma chave. Sem ela,
duas linhas repetidas de um lado e duas do outro poderiam produzir quatro linhas
no resultado.

Além dessa proteção do Pandas, o código compara a quantidade de linhas antes e
depois de cada junção. Qualquer perda ou multiplicação interrompe a execução.

### `indicator=True`

Antes do merge definitivo, uma junção auxiliar `outer` usa `indicator=True`. O
Pandas cria a coluna `_merge` com três resultados possíveis:

- `both`: a chave apareceu nas duas fontes;
- `left_only`: apareceu apenas no PLD;
- `right_only`: apareceu apenas na fonte da direita.

O relatório usa `left_only` para mostrar observações do PLD sem correspondência
na fonte e `right_only` para mostrar observações da fonte sem PLD. Estas últimas
não entram no resultado porque o merge definitivo continua sendo `left` com o
PLD à esquerda. A coluna auxiliar `_merge` não é gravada no arquivo final.

## Ausências encontradas na integração

Na execução de 11/10/2026, foram preservadas as 8.388 linhas do PLD. As coberturas
mais recentes eram diferentes:

| Fonte | Última data | Chaves do PLD sem correspondência |
| --- | --- | ---: |
| PLD | 11/10/2026 | — |
| Carga | 09/10/2026 | 8 |
| EAR | 10/10/2026 | 4 |
| ENA | 10/10/2026 | 4 |
| Balanço | 09/10/2026 | 8 |

Cada dia representa quatro chaves, uma por submercado. Assim, as oito ausências
de carga correspondem aos quatro submercados em 10/10 e 11/10. As quatro
ausências de EAR correspondem aos quatro submercados em 11/10.

Esses valores nulos não significam automaticamente erro. Neste caso, eles
refletem datas finais diferentes nas atualizações das fontes. O código os relata,
mas não remove as linhas do PLD e não inventa valores para o ONS.

Após uma nova coleta, essas contagens podem mudar. Por isso, os testes verificam
a correspondência com os arquivos atuais, em vez de fixar esses números para
sempre.

## Construção explícita do alvo `pld_d1`

O objetivo de `pld_d1` é representar o preço do próximo dia do calendário para o
mesmo submercado.

Primeiro, o código cria a data que queremos prever:

```python
df_treino["data_alvo"] = df_treino["data"] + pd.Timedelta(days=1)
```

Depois, cria uma pequena tabela de consulta:

```python
alvos = dataframe[["data", "submercado", "pld_medio_dia"]].rename(
    columns={
        "data": "data_alvo",
        "pld_medio_dia": "pld_d1",
    }
)
```

Por fim, busca o preço cuja `data_alvo` e cujo `submercado` sejam iguais:

```python
df_treino = df_treino.merge(
    alvos,
    on=["data_alvo", "submercado"],
    how="left",
    validate="one_to_one",
)
```

### Por que não usar apenas `shift(-1)`

`shift(-1)` pega a próxima linha existente, não necessariamente o próximo dia do
calendário. Considere esta sequência:

```text
06/08/2021 → existe
07/08/2021 → ausente no PLD publicado
08/08/2021 → existe
```

Um deslocamento simples poderia associar 06/08 ao preço de 08/08. O merge
explícito procura exatamente 07/08 e, como essa data não existe, mantém `pld_d1`
nulo. Isso representa corretamente a lacuna da fonte.

Na execução analisada, existem 28 alvos ausentes: quatro submercados para cada
uma das seis lacunas históricas que possuem um dia anterior no conjunto, mais os
quatro registros da última data, cujo dia seguinte ainda não está disponível.

## Data de referência não é data de disponibilidade

Uma variável com data de referência D descreve o que aconteceu no dia D. Isso
não garante que ela já estivesse publicada no instante em que a previsão de D+1
seria produzida.

Exemplo: suponha que a previsão do PLD de amanhã seja feita hoje às 18h. Uma carga
chamada “carga do dia de hoje” pode depender das horas entre 18h e 23h e só ser
publicada depois da meia-noite. Nesse cenário, usar a carga completa de hoje para
prever amanhã permitiria que o modelo enxergasse uma informação que o previsor
real ainda não possuía.

O mesmo cuidado vale para:

- EAR e ENA verificadas do dia;
- geração hidráulica, térmica, eólica e solar;
- intercâmbio e carga calculados pelas 24 horas do balanço;
- o próprio PLD do dia D, dependendo do horário escolhido para a previsão.

Esse problema é chamado de **vazamento temporal**. Ele pode produzir métricas
artificialmente boas, mas que não seriam reproduzíveis em uma operação real.

Por isso, `pld_treino.parquet` significa apenas “histórico com alvo anexado”. O
nome não afirma que todas as suas colunas podem ser usadas imediatamente como
features.

## Testes da integração

O arquivo `tests/test_integracao_datasets.py` possui dois testes:

- `test_integracao_datasets()` verifica dimensões, período, submercados,
  duplicatas, nomes das colunas, ausências e preservação dos valores originais;
- `test_preparacao_pld_d1()` verifica se `data_alvo` é exatamente D+1 e se
  `pld_d1` corresponde ao PLD daquela data e daquele submercado.

Para gerar os arquivos e executar apenas esses testes:

```powershell
python src\merge.py
python -m pytest tests\test_integracao_datasets.py -q -s
```

Para executar toda a suíte:

```powershell
python -m pytest -q
```

As ausências das fontes do ONS são impressas como diagnóstico, mas não fazem o
teste falhar automaticamente. O teste falha se o merge alterar o PLD, multiplicar
linhas, criar sufixos automáticos ou copiar incorretamente valores das fontes.

## Etapas necessárias antes do treinamento

Antes de implementar um modelo, ainda será necessário:

1. definir o horário e a regra operacional da previsão D+1;
2. pesquisar quando cada fonte publica ou disponibiliza seus dados;
3. decidir quais variáveis podem ser usadas no mesmo dia e quais precisam de
   defasagem;
4. tratar conscientemente as ausências, sem usar informação futura;
5. estudar redundâncias, como as duas medidas de carga;
6. criar features em uma etapa separada;
7. definir divisões temporais de treino, validação e teste;
8. somente então treinar e avaliar modelos.

