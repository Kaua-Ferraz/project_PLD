# Automação da coleta prospectiva

Este documento explica como executar automaticamente, duas vezes por dia, o
mesmo comando auditável já usado manualmente:

```powershell
pld collect daily --snapshot
```

A automação não possui um segundo coletor. `automation.py` apenas envolve o
comando acima com lock, retentativas, logs de execução, auditoria de horários
perdidos e medição de armazenamento. Assim, as validações, o manifesto,
os hashes e os snapshots continuam sendo responsabilidade dos coletores já
testados em `src/pld_forecast/collectors/`.

[Voltar ao README principal](../README.md)

## O que é coletado

Cada execução consulta todos os datasets mantidos pelo projeto:

- CCEE: `pld_media_diaria` e `pld_horario`;
- ONS: `carga-energia`, `ear-diario-por-subsistema`,
  `ena-diario-por-subsistema` e `balanco-energia-subsistema`.

Isso inclui os quatro datasets exigidos para o fluxo horário — PLD horário,
balanço horário, EAR e ENA — e preserva os coletores diário e de carga existentes.

## Horário programado e horário real

As tarefas são programadas para 11:45 e 20:30 no horário local do Windows. O
instalador exige o fuso `E. South America Standard Time`, que corresponde a
`America/Sao_Paulo` no projeto.

Esses horários não são usados como horário de captura. Cada `metadata.json` do
snapshot recebe `collection_time` no instante em que aquele arquivo foi
efetivamente copiado. O registro da execução também separa:

- `scheduled_for`: horário que deveria iniciar a tarefa;
- `actual_started_at`: início real do processo;
- `completed_at`: término real;
- `duration_seconds`: duração observada.

Por exemplo, uma execução marcada para 11:45 e iniciada às 12:07 registra os
dois instantes. Ela não serve como evidência de que o dado estava disponível
antes das 12:00.

## Instalação

Primeiro crie o ambiente virtual e instale o projeto, se isso ainda não foi
feito:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Na raiz do projeto, registre as duas tarefas:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_scheduled_tasks.ps1
```

O instalador:

1. confirma o ambiente virtual e o fuso do Windows;
2. cria as tarefas `PLD - Coleta prospectiva - 1145` e
   `PLD - Coleta prospectiva - 2030`;
3. configura o diretório de trabalho na raiz do projeto;
4. usa especificamente `.venv\Scripts\python.exe`;
5. impede instâncias paralelas também no Agendador;
6. habilita execução assim que possível após um horário perdido;
7. configura duas novas tentativas do Agendador, separadas por 15 minutos;
8. registra em `data/automation/schedule.json` quando a auditoria começou.

As tarefas usam o token interativo do usuário atual para manter acesso normal à
rede sem guardar uma senha. Portanto, precisam que esse usuário esteja com uma
sessão iniciada. Se o computador estava desligado ou o usuário desconectado, a
opção “iniciar assim que possível” executa a tarefa no retorno, mas o horário
real continuará sendo registrado. Uma instalação para executar sem login exige
configurar uma conta e credenciais apropriadas manualmente no Agendador; antes
disso, deve-se testar se essa conta tem acesso à internet e ao diretório do projeto.

## Verificar, ativar e desativar

```powershell
# Estado, próximo horário, último resultado, comando e diretório de trabalho
powershell -ExecutionPolicy Bypass -File scripts\manage_scheduled_tasks.ps1 status

# Reativar as duas tarefas
powershell -ExecutionPolicy Bypass -File scripts\manage_scheduled_tasks.ps1 enable

# Pausar sem apagar a configuração
powershell -ExecutionPolicy Bypass -File scripts\manage_scheduled_tasks.ps1 disable

# Remover as duas tarefas do Windows
powershell -ExecutionPolicy Bypass -File scripts\manage_scheduled_tasks.ps1 remove
```

Desativar ou remover as tarefas não apaga dados, snapshots, logs ou manifestos.

## Executar e testar manualmente

O mesmo wrapper usado pelo Agendador pode ser testado sem esperar o próximo
horário:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_prospective_collection.ps1 `
  -Slot manual -MaxAttempts 1 -RetryDelaySeconds 1
```

Para auditar horários agendados sem execução:

```powershell
.venv\Scripts\python.exe -m pld_forecast.automation audit
```

Para atualizar somente o relatório de espaço:

```powershell
.venv\Scripts\python.exe -m pld_forecast.automation storage
```

## Arquivos produzidos

```text
data/
├── manifest.json
├── snapshots/<horário UTC>/.../metadata.json
└── automation/
    ├── schedule.json
    ├── runs/<execução>.json
    ├── missed_runs.json
    ├── missed_run_events.jsonl
    └── storage_report.json

logs/collection/<data>/<execução>.log
```

O log textual contém início, término, duração, datasets consultados, todas as
mensagens dos coletores, arquivos atualizados e erros. O JSON de `runs/` resume
o resultado de forma fácil de ler por código. O manifesto e cada
`metadata.json` continuam registrando `resource_id`, SHA-256 e o instante real
de captura por arquivo.

`missed_runs.json` mostra as ocorrências atualmente ausentes. A auditoria espera
duas horas após cada horário antes de marcá-lo como perdido, para não confundir
uma coleta longa com uma coleta que nunca começou. O arquivo JSONL preserva os
eventos `missed` e `resolved`; uma execução atrasada pode resolver o alerta, mas
não muda o horário real de captura.

## Concorrência e falhas

Existem duas proteções contra concorrência:

- o Agendador usa `MultipleInstances = IgnoreNew`;
- o Python cria exclusivamente `data/automation/collection.lock`.

Se o processo morrer, um lock com mais de seis horas e cujo PID já não existe é
renomeado com o sufixo `.stale-<timestamp>` antes da recuperação. Ele é
preservado para auditoria.

O cliente CKAN já repete falhas transitórias de HTTP. Além disso, o wrapper faz
até duas tentativas completas, com cinco minutos de intervalo. Cada tentativa
usa um novo diretório de snapshot; uma tentativa parcial nunca sobrescreve uma
captura anterior. O Agendador ainda pode reiniciar uma execução que terminou
com erro. Essa repetição em camadas é intencional: a primeira trata uma requisição
instável, a segunda trata uma coleta incompleta e a terceira trata uma falha do
processo agendado.

## Armazenamento e backup

Depois de cada execução, `storage_report.json` registra o tamanho de snapshots,
backups e logs, além do espaço livre no disco. Não existe exclusão automática.
Isso é importante porque uma versão antiga pode ser a única prova do conjunto
de dados disponível em um instante da pesquisa.

Estratégia recomendada:

1. manter a cópia de trabalho no computador;
2. fazer backup incremental diário de `data/snapshots/`, `data/raw/**/backups/`,
   `data/manifest.json`, `data/automation/` e `logs/`;
3. manter uma segunda cópia semanal em outro dispositivo ou armazenamento
   institucional criptografado;
4. verificar periodicamente os SHA-256 registrados nos metadados;
5. versionar o código no Git, mas não os grandes arquivos de dados;
6. nunca usar sincronização com opção de espelhamento/exclusão como única cópia.

Antes de mover ou reduzir qualquer conjunto de dados, registre a decisão no
protocolo da pesquisa e confirme que existem pelo menos duas cópias verificadas.

## Testes automatizados

```powershell
python -m pytest tests/test_automation.py -q
```

Os testes usam pastas temporárias e um coletor simulado; não acessam os portais.
Eles verificam o vínculo entre slot e início real, o lock simultâneo, a
recuperação auditável de lock abandonado, as retentativas, os registros de
execução, a detecção e resolução de horários perdidos e a medição sem exclusão.
