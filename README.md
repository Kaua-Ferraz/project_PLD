# Previsão do PLD Médio Diário

Projeto de Iniciação Científica voltado à previsão do Preço de Liquidação das Diferenças (PLD) médio diário utilizando técnicas de Machine Learning.

O projeto ainda está em desenvolvimento. A etapa atualmente implementada é a coleta confiável e incremental dos dados que serão usados nas etapas posteriores de análise, preparação e treinamento dos modelos.

## Fontes de dados

Os dados são obtidos principalmente de dois portais públicos que utilizam APIs CKAN:

- [CCEE — Dados Abertos](https://dadosabertos.ccee.org.br), incluindo o PLD médio diário;
- [ONS — Dados Abertos](https://dados.ons.org.br), incluindo carga, energia armazenada, energia natural afluente e balanço de energia por subsistema.

## Estado atual

Nesta fase, o projeto oferece:

- coleta histórica a partir de 2021;
- atualização diária dos recursos do ano atual;
- detecção de alterações por metadados e SHA-256;
- validação dos CSVs antes da substituição;
- backups e recuperação em caso de falha;
- registro local em `data/manifest.json`;
- testes automatizados sem dependência obrigatória dos servidores externos.

A preparação final dos dados e o treinamento dos modelos ainda não fazem parte desta versão.

## Estrutura do projeto

```text
project_PLD/
├── docs/
│   └── coleta_dados.md     # documentação completa do coletor
├── notebooks/               # explorações e experimentos futuros
├── src/
│   ├── data/
│   │   ├── ckan.py
│   │   ├── ccee.py
│   │   ├── ons.py
│   │   └── validate.py
│   └── update.py
├── tests/
├── .gitignore
├── README.md
└── requirements.txt
```

Os datasets baixados ficam em `data/`, mas não são enviados ao Git porque podem ser reconstruídos executando a coleta.

## Instalação

Na raiz do projeto, instale as dependências:

```powershell
python -m pip install -r requirements.txt
```

Para realizar a primeira coleta histórica:

```powershell
python -m src.update historical
```

Para verificar apenas as atualizações mais recentes:

```powershell
python -m src.update daily
```

Para executar os testes:

```powershell
python -m pytest -q
```

## Documentação da coleta

A explicação completa do coletor — incluindo arquitetura, comandos, manifesto, detecção de alterações, validações, duplicatas e backups — está em [docs/coleta_dados.md](docs/coleta_dados.md).
