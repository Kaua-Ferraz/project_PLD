# Pré-modelagem e disponibilidade temporal

## Features horárias da Etapa 2

O fluxo diário detalhado abaixo foi preservado. Quando existem alvos horários,
`pld features` executa também `create_hourly_features()` e cria
`data/processed/pld_horario_features.parquet`. Cada linha mantém
`issue_time`, `target_time`, `horizon`, `submercado` e `target_pld`.

- `price.py` consulta o último preço de referência até a emissão, os lags
  exatos de 24h, 48h e 168h em relação ao alvo e as médias/desvios das
  janelas anteriores à emissão. Um lag futuro fica nulo, não é antecipado.
- `calendar.py` acrescenta hora-alvo, seno/cosseno da hora, dia da semana,
  fim de semana, mês e a convenção sazonal maio–outubro = seco, novembro–abril
  = úmido. Essa convenção não substitui medições hidrológicas.
- `load_gen.py` e `hydrology.py` consultam carga, balanço, EAR e ENA nos
  Parquets consolidados pela data de referência D-2 do dia de emissão. O
  balanço horário usa a hora do alvo, mas do dia histórico permitido;
  intercâmbio conserva o sinal. EAR absoluta (MWmês) e percentual e ENA
  absoluta (MWmed) e percentual da MLT permanecem distintas.

As colunas terminadas em `_reference_time` tornam auditável de qual instante
veio cada medida. A classificação de nulos vai para
`pld_horario_features_diagnostico.parquet`: início da série, hora histórica
sem PLD, ausência original, lacuna da fonte, fim ainda não publicado,
indisponibilidade na emissão e janela com apenas uma amostra para o desvio.
Nenhum `fillna(0)` ou `dropna()` é aplicado às features. A divisão cronológica
segue `target_time`: treino até 2024, validação em 2025, teste desde 2026.
Esses rótulos não impedem que um futuro walk-forward defina cortes próprios.

Há uma limitação científica importante: o histórico consolidado atual não
contém versões *as of* de cada publicação. O atraso D-2 reduz o risco de usar
um dia ainda não encerrado, mas não elimina viés de revisão. Nos testes, uma
fonte com `collection_time` pode usar esse horário para selecionar somente
registros já coletados; para repetir isso na pesquisa real é necessário
materializar os snapshots por emissão.

Este documento explica a etapa diária implementada em
`src/pld_forecast/features/engine.py` (`src/features.py` continua como caminho
de compatibilidade). Ela valida o
resultado da integração, define um cenário de previsão, cria features temporais
simples, diagnostica valores ausentes e prepara uma divisão cronológica.

Nenhum modelo é treinado. Nenhum `NaN` é preenchido e nenhuma linha é removida.

[Voltar ao README principal](../README.md) ·
[Ver a integração dos dados](integracao_dados.md)

## 1. Diagnóstico do dataset final

Na execução de 12/10/2026, `pld_integrado.parquet` apresentou:

| Informação | Resultado |
| --- | --- |
| Período | 08/01/2021 a 11/10/2026 |
| Linhas | 8.388 |
| Submercados | NORTE, NORDESTE, SUDESTE e SUL |
| Linhas por submercado | 2.097 |
| Duplicatas por data e submercado | 0 |

Registros por ano:

| Ano | Registros |
| ---: | ---: |
| 2021 | 1.424 |
| 2022 | 1.444 |
| 2023 | 1.460 |
| 2024 | 1.464 |
| 2025 | 1.460 |
| 2026, até 11/10 | 1.136 |

As contagens são múltiplas de quatro porque cada data possui uma linha por
submercado. Os anos de 2021 e 2022 têm menos linhas devido ao início da série e
às seis datas ausentes do PLD, já documentadas na etapa de integração.

### Cobertura das fontes

| Fonte | Primeira data | Última data | Registros |
| --- | --- | --- | ---: |
| PLD | 08/01/2021 | 11/10/2026 | 8.388 |
| Carga | 01/01/2021 | 09/10/2026 | 8.432 |
| EAR | 01/01/2021 | 10/10/2026 | 8.436 |
| ENA | 01/01/2021 | 10/10/2026 | 8.436 |
| Balanço | 01/01/2021 | 09/10/2026 | 8.432 |

Por isso, as ausências originais do integrado estão apenas no fim da série:

- 8 valores por coluna de carga e balanço: quatro submercados em 10 e 11/10;
- 4 valores por coluna de EAR e ENA: quatro submercados em 11/10;
- nenhum valor ausente no PLD de D.

Em `pld_treino.parquet`, existem 28 `pld_d1` ausentes:

- 24 correspondem a seis datas históricas sem PLD, vezes quatro submercados;
- 4 correspondem a 12/10/2026, que estava além do fim da série no momento da
  execução.

Essas ausências são relatadas, não corrigidas.

## 2. Data de referência e data de disponibilidade

São conceitos diferentes:

- **data de referência**: dia que o valor descreve;
- **data de disponibilidade**: instante em que o arquivo ou valor pôde ser
  consultado;
- **instante de previsão**: corte temporal depois do qual o modelo não pode
  receber informação alguma.

Uma carga identificada como 10/10 descreve o dia 10/10. Como ela é uma média do
dia inteiro, não pode estar completa às 15h do próprio dia. Se usarmos hoje a
versão histórica final dessa carga como se ela já estivesse disponível às 15h,
produzimos vazamento temporal.

Há ainda o **viés de revisão**: o ONS informa que os dados passam por
consistência recorrente e podem ser atualizados depois da publicação. Um
Parquet baixado hoje pode conter uma revisão que não existia na data histórica
da previsão. Somente snapshots versionados por horário permitem reconstruir
perfeitamente esse estado passado.

## 3. O que as fontes oficiais permitem concluir

A CCEE determina que o PLD horário seja calculado e divulgado diariamente até
as 20h, com vigência para as 24 horas do dia seguinte. Portanto, o PLD de D é
conhecido até 20h de D-1. O PLD médio diário usado aqui é a média desses preços
horários por submercado.

O portal de dados abertos da CCEE, porém, classifica o arquivo histórico de
`PLD_MEDIA_DIARIA` com frequência de atualização mensal. Assim, há uma diferença
entre o preço oficial estar conhecido e este CSV histórico específico estar
atualizado. Para operação diária, será necessário confirmar o acesso ao canal
de publicação diária ou registrar snapshots dele.

Os quatro datasets do ONS informam atualização às 12h e 19h. As páginas não
garantem qual é a última **data de referência completa** presente em cada
atualização. O snapshot local mostrou EAR e ENA até D-1, mas carga e balanço
apenas até D-2. Isso é evidência observada, não uma garantia para todos os dias.

Fontes oficiais consultadas:

- [Procedimento de Comercialização da CCEE — divulgação do PLD](https://www.ccee.org.br/o/ccee/documentos/CCEE_1031303)
- [PLD médio diário — Dados CCEE](https://dadosabertos.ccee.org.br/dataset/pld_media_diaria)
- [Carga de energia diária — ONS](https://dados.ons.org.br/dataset/carga-energia)
- [EAR diária por subsistema — ONS](https://dados.ons.org.br/dataset/ear-diario-por-subsistema)
- [ENA diária por subsistema — ONS](https://dados.ons.org.br/dataset/ena-diario-por-subsistema)
- [Balanço de energia nos subsistemas — ONS](https://dados.ons.org.br/dataset/balanco-energia-subsistema)

## 4. Tabela de disponibilidade temporal

O cenário da tabela é a previsão às **00h de D** para o PLD médio de D+1.

| Variável | Fonte | Granularidade original | Referência | Disponibilidade estimada | Usar D? | Usar D-1? | Decisão atual |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PLD | CCEE | horária; média diária no projeto | dia de vigência | divulgado até 20h de D-1 | sim, conceitualmente | sim | D e lags 1, 2 e 7; acesso diário ao CSV ainda deve ser confirmado |
| Carga | ONS | diária, MWmed | dia medido | portal atualiza 12h/19h; atraso exato incerto | não | incerto às 00h | D-2 provisório |
| EAR máxima, absoluta e % | ONS | diária, MWmês e % | dia verificado | portal atualiza 12h/19h; atraso exato incerto | não | incerto às 00h | D-2 provisório |
| ENA bruta/armazenável | ONS | diária, MWmed e % MLT | dia verificado | portal atualiza 12h/19h; atraso exato incerto | não | incerto às 00h | D-2 provisório |
| Geração hidráulica | ONS | horária, agregada por média | hora/dia verificado | exige o fechamento das 24h; publicação exata incerta | não | incerto às 00h | D-2 provisório |
| Geração térmica | ONS | horária, agregada por média | hora/dia verificado | exige o fechamento das 24h; publicação exata incerta | não | incerto às 00h | D-2 provisório |
| Geração eólica | ONS | horária, agregada por média | hora/dia verificado | exige o fechamento das 24h; publicação exata incerta | não | incerto às 00h | D-2 provisório |
| Geração solar | ONS | horária, agregada por média | hora/dia verificado | exige o fechamento das 24h; publicação exata incerta | não | incerto às 00h | D-2 provisório |
| Intercâmbio | ONS | horário, agregado por média com sinal | hora/dia verificado | exige o fechamento das 24h; publicação exata incerta | não | incerto às 00h | D-2 provisório |

O valor de D-2 foi escolhido para preparar a estrutura, não para declarar a
investigação encerrada. Antes de uma avaliação operacional definitiva, devemos
registrar por vários dias o horário de download, a última data presente e o hash
de cada recurso. Isso permitirá verificar se D-2 realmente estava disponível em
cada instante histórico equivalente.

## 5. Cenários de previsão

### Cenário implementado: 00h de D

Objetivo: prever o PLD médio de D+1 no início de D.

- PLD de D: já foi divulgado pela CCEE no dia anterior;
- calendário de D+1: conhecido;
- valores verificados do ONS de D: impossíveis, pois D acabou de começar;
- valores do ONS de D-1: podem ainda não ter sido publicados ou consolidados;
- valores do ONS de D-2: usados provisoriamente como escolha conservadora.

### Cenário alternativo: depois da atualização das 19h de D

Esse cenário talvez permita usar informações mais recentes do ONS. Entretanto,
ele cria duas dificuldades:

1. o portal não garante qual data de referência entrou às 19h;
2. o PLD de D+1 pode já ter sido divulgado, porque 20h é um prazo máximo, não
   necessariamente o horário exato de todos os dias.

Por essas razões, esse cenário não foi implementado silenciosamente. Ele exige
snapshots com timestamp da CCEE e do ONS.

## 6. Features implementadas

`src/features.py` cria:

- `pld_medio_dia`: PLD de D, usado também pelo baseline;
- `pld_medio_dia_lag_1d`, `lag_2d` e `lag_7d`;
- lag D-2 das 14 variáveis do ONS;
- `dia_semana_alvo`, `mes_alvo` e `fim_de_semana_alvo` para D+1;
- `baseline_pld_d1`, igual ao PLD de D;
- `conjunto_temporal`, com treino, validação ou teste.

As colunas atuais do ONS não são copiadas para o arquivo de features. Isso reduz
o risco de um modelo futuro usar por acidente um valor verificado de D.

### Por que o lag é feito por data

O código não usa `shift()`:

```python
lookup["data"] = lookup["data"] + pd.Timedelta(days=lag_days)

result = dataframe.merge(
    lookup,
    on=["data", "submercado"],
    how="left",
    validate="one_to_one",
)
```

Exemplo:

```text
01/01 existe: valor 100
02/01 ausente
03/01 existe: valor 120
```

Para a linha de 03/01, `lag1` procura exatamente 02/01 e retorna `NaN`.
`shift(1)` pegaria a linha anterior existente, 01/01, e chamaria incorretamente
esse valor de D-1.

O histórico usado para consultar os lags é a união dos cinco Parquets
consolidados. Isso é importante porque o integrado é ancorado no PLD: uma data
sem PLD não aparece nele, embora o ONS possa possuir aquela data. As linhas do
arquivo final continuam sendo exatamente as linhas do PLD.

## 7. Valores ausentes depois das features

As causas são classificadas como:

- `inicio_da_serie`;
- `dia_historico_sem_pld`;
- `ausencia_original_da_fonte`;
- `lacuna_historica_da_fonte`;
- `fim_da_serie_nao_publicado`.

Na execução analisada, os lags D-2 do ONS ficaram completos porque os Parquets
do ONS começam sete dias antes do PLD. As ausências restantes vieram do alvo e
dos lags do próprio PLD.

Se exigíssemos alvo e todas as features completas, 116 linhas seriam removidas:

| Ano da data-alvo | Linhas |
| ---: | ---: |
| 2021 | 60 |
| 2022 | 52 |
| 2026 | 4 |

São 29 linhas por submercado. `src/features.py` apenas mostra esse diagnóstico;
as 116 linhas continuam no arquivo. A decisão de montar uma amostra completa
deve ser tomada junto com o modelo e sua capacidade de lidar com ausências.

Não foi aplicado `fillna(0)`: zero seria um valor físico, não a representação
correta de “desconhecido”. Também não houve interpolação ou `dropna()`.

## 8. Divisão cronológica

A divisão usa `data_alvo`, isto é, o dia que será previsto:

| Conjunto | Datas-alvo | Linhas atuais |
| --- | --- | ---: |
| Treino | até 31/12/2024 | 5.788 |
| Validação | 01/01/2025 a 31/12/2025 | 1.460 |
| Teste | a partir de 01/01/2026 | 1.140 |

Não há embaralhamento. Os lags são calculados no histórico completo antes da
marcação dos períodos. Isso permite que o primeiro dia da validação consulte um
dia anterior do treino, como ocorreria na operação real, mas nunca consulta uma
data futura.

O teste de 2026 ainda é parcial e crescerá com novas coletas. Quando a avaliação
começar, será importante congelar a data final do teste para comparar modelos
sob o mesmo período.

## 9. Baseline

O baseline implementado é:

```text
previsão do PLD de D+1 = PLD conhecido de D
```

Em código:

```python
result["baseline_pld_d1"] = result["pld_medio_dia"]
```

Ele é uma referência mínima. Um modelo mais complexo só será útil se superar
consistentemente essa regra em dados futuros. Nenhuma métrica foi calculada
nesta etapa.

## 10. Como executar

Depois de `src/merge.py`:

```powershell
python -m src.features
```

O comando cria `data/processed/pld_features.parquet` e imprime os diagnósticos.
Para executar apenas os novos testes:

```powershell
python -m pytest tests\test_pre_modelagem.py tests\test_features.py -q -s
```

O arquivo de features ainda não deve ser tratado como base operacional final,
pois a disponibilidade ponto a ponto do ONS e a atualização diária do caminho
de PLD precisam ser confirmadas.

## 11. Estado do pipeline

```text
Aquisição                  concluída
Limpeza                    concluída
Consolidação               concluída
Integração                 concluída
Alvo D+1                   concluído
Disponibilidade temporal   analisada; latência do ONS ainda incerta
Features                   preparada com hipótese D-2 explícita
Tratamento de NaN          diagnosticado; nenhuma remoção aplicada
Divisão temporal           preparada
Baseline                   preparado
Modelagem                  ainda não iniciada
```

Antes da modelagem faltam: validar snapshots de publicação, decidir o tratamento
das 116 linhas incompletas, congelar o período de teste e definir métricas de
avaliação adequadas.

