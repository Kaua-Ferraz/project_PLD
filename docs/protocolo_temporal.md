# Protocolo temporal da previsão horária

[Voltar ao README](../README.md)

Uma previsão precisa usar apenas o que se sabia no momento em que foi emitida.
Por isso, guardamos três horários distintos:

| Campo | Pergunta respondida | Exemplo |
| --- | --- | --- |
| `reference_time` | A que hora o valor se refere? | PLD de 10/01 às 08h |
| `collection_time` | Quando capturamos o arquivo que contém esse valor? | 09/01 às 10h |
| `issue_time` | Quando a previsão foi emitida? | 09/01 às 12h |

O cenário horário inicial usa `issue_time` às 12h de D-1 para prever as 24
horas de D. As horas previstas vão de H+12 a H+35. O horário pode ser mudado
com `issue_time_for_target()` em `src/pld_forecast/config.py`.

`validate_availability()` bloqueia `reference_time > issue_time` e
`collection_time > issue_time`. Sem snapshot histórico, ela exige uma
defasagem explícita. Por exemplo, com emissão às 12h de 09/01 e lag histórico
de dois dias para o ONS, referências até 07/01 passam; 08/01 não passa. Essa
regra é uma **hipótese conservadora**, não uma prova do horário real de
publicação. Os snapshots capturados prospectivamente poderão fornecer essa
prova nas próximas etapas.

No código, a conta é uma comparação de datas de calendário:

```python
cutoff_day = issue.normalize() - pd.Timedelta(days=historical_lag_days)
if reference.normalize() > cutoff_day:
    raise ValueError("reference_time viola a defasagem histórica")
```

`normalize()` mantém a data e coloca a hora em 00:00. Isso permite aplicar a
defasagem D-2 a variáveis diárias sem tomar uma linha anterior por posição.
Os alvos e lags continuam a usar chaves temporais explícitas e `merge()`.

Os comandos `pld integrate` e `pld features` preservam a preparação diária e
também executam a horária quando o PLD horário está disponível. O backtest,
a previsão e a avaliação dos modelos são etapas seguintes.

Na preparação horária, `target_time = issue_time + horizon` é conferido em
cada linha. Para 12h de D-1, H+12..H+35 representam as 24 horas de D.
O lag de PLD em `target_time - 24h` só entra se sua referência for anterior
ou igual à emissão. Por isso, H+35 não recebe esse lag em uma emissão H+0
às 12h; o valor futuro fica nulo com diagnóstico
`indisponivel_na_emissao`. Carga, EAR, ENA e balanço usam D-2 do dia de
emissão no backtest histórico. Quando uma fonte de teste inclui
`collection_time`, o código também bloqueia coletas posteriores à emissão.

Importante: os Parquets históricos consolidados não carregam a data de cada
publicação ou revisão passada. Logo, D-2 continua sendo hipótese conservadora,
não prova de disponibilidade ex ante nem proteção completa contra revisões.
O mesmo vale para o preço horário histórico consultado pela referência
`<= issue_time`. Uma avaliação operacional definitiva exigirá reconstrução
por snapshots de cada emissão. O arquivo integrado preserva valores ONS do
instante-alvo apenas para diagnóstico; a feature engine não os copia.
