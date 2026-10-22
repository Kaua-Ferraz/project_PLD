"""Integração dos datasets e preparação explícita do alvo PLD D+1."""

from pathlib import Path

import pandas as pd

from ..config import SUBMARKETS

try:
    from .pipeline import (
        save_parquet,
        sort_dataframe,
        validate_input_dataframe,
        validate_no_missing_values,
        validate_unique_keys,
    )
except ImportError:
    from pipeline import (
        save_parquet,
        sort_dataframe,
        validate_input_dataframe,
        validate_no_missing_values,
        validate_unique_keys,
    )


def merge_datasets() -> pd.DataFrame:
    """Integra os cinco datasets usando o PLD como tabela principal.

    Os registros do PLD são preservados por meio de junções à esquerda. Dados
    sem correspondência nas fontes do ONS permanecem nulos para investigação.
    O histórico integrado é salvo em ``data/processed/pld_integrado.parquet``.
    """
    raiz = Path(__file__).resolve().parents[3]
    pasta = raiz / "data" / "interim"

    df_pld = pd.read_parquet(pasta / "pld.parquet")
    df_carga = pd.read_parquet(pasta / "carga_energia.parquet")
    df_ear = pd.read_parquet(pasta / "ear.parquet")
    df_ena = pd.read_parquet(pasta / "ena.parquet")
    df_balanco = pd.read_parquet(pasta / "balanco_energia.parquet")

    datasets = {
        "PLD": df_pld,
        "Carga": df_carga,
        "EAR": df_ear,
        "ENA": df_ena,
        "Balanço": df_balanco,
    }

    chaves = ["data", "submercado"]

    for nome, dataframe in datasets.items():
        print(f"\n--- {nome} ---")
        print("Dimensões:", dataframe.shape)
        print("Colunas:", dataframe.columns.tolist())

        if dataframe.columns.duplicated().any():
            raise ValueError(f"{nome}: existem nomes de colunas duplicados!")

        validate_input_dataframe(dataframe, set(chaves), nome)

        print("Período:", dataframe["data"].min(), "até", dataframe["data"].max())
        print("Tipos das chaves:", dataframe[chaves].dtypes.to_dict())

        validate_no_missing_values(dataframe, chaves, f"chaves de {nome}")
        validate_unique_keys(dataframe, chaves, nome)

        if not pd.api.types.is_datetime64_any_dtype(dataframe["data"]):
            raise TypeError(f"{nome}: a coluna data não possui tipo de data!")

        if not pd.api.types.is_string_dtype(dataframe["submercado"]):
            raise TypeError(f"{nome}: a coluna submercado não possui tipo textual!")

        datas_com_horario = dataframe["data"] != dataframe["data"].dt.normalize()

        if datas_com_horario.any():
            raise ValueError(f"{nome}: existem horários na chave diária data!")

        # Alguns Parquets retornam o texto como "str" e outros como "string".
        # Ambos são textuais, mas a conversão deixa a chave igual antes do merge.
        dataframe = dataframe.copy()
        dataframe["submercado"] = dataframe["submercado"].astype("string")
        datasets[nome] = dataframe

    df_pld = datasets["PLD"]
    colunas_integradas = set(df_pld.columns) - set(chaves)

    for nome, dataframe in datasets.items():
        if nome == "PLD":
            continue

        colunas_novas = set(dataframe.columns) - set(chaves)
        colunas_repetidas = colunas_integradas.intersection(colunas_novas)

        if colunas_repetidas:
            raise ValueError(
                f"{nome}: colunas conflitantes antes do merge: "
                + ", ".join(sorted(colunas_repetidas))
            )

        colunas_integradas.update(colunas_novas)

    df_final = df_pld.copy()

    for nome, dataframe in datasets.items():
        if nome == "PLD":
            continue

        linhas_antes = len(df_final)

        correspondencias = df_pld[chaves].merge(
            dataframe[chaves],
            on=chaves,
            how="outer",
            indicator=True,
            validate="one_to_one",
        )
        sem_correspondencia = correspondencias[
            correspondencias["_merge"] == "left_only"
        ]
        somente_na_fonte = correspondencias[
            correspondencias["_merge"] == "right_only"
        ]

        print(
            f"{nome}: chaves do PLD sem correspondência:",
            len(sem_correspondencia),
        )
        if not sem_correspondencia.empty:
            print(sem_correspondencia[chaves].head(20).to_string(index=False))

        print(
            f"{nome}: chaves da fonte sem PLD:",
            len(somente_na_fonte),
        )
        if not somente_na_fonte.empty:
            print(somente_na_fonte[chaves].head(20).to_string(index=False))

        df_final = df_final.merge(
            dataframe,
            on=chaves,
            how="left",
            validate="one_to_one",
        )

        if len(df_final) != linhas_antes:
            raise ValueError(
                f"O merge com {nome} alterou a quantidade de linhas!"
            )

        print(f"{nome} integrado com sucesso!")

    if df_final.columns.duplicated().any():
        raise ValueError("O resultado possui nomes de colunas duplicados!")

    colunas_com_sufixo = [
        coluna
        for coluna in df_final.columns
        if coluna.endswith("_x") or coluna.endswith("_y")
    ]

    if colunas_com_sufixo:
        raise ValueError(
            "O Pandas criou sufixos por conflito de colunas: "
            + ", ".join(colunas_com_sufixo)
        )

    validate_unique_keys(df_final, chaves, "resultado integrado")

    print("\n--- Valores ausentes após integração ---")
    print(df_final.isna().sum())

    colunas_dados = [
        coluna
        for coluna in df_final.columns
        if coluna not in chaves
    ]
    linhas_incompletas = df_final[
        df_final[colunas_dados].isna().any(axis=1)
    ]

    print("\nLinhas com dados ausentes:", len(linhas_incompletas))
    if not linhas_incompletas.empty:
        print(linhas_incompletas.head(20).to_string(index=False))

    df_final = sort_dataframe(df_final, chaves)

    destino = raiz / "data" / "processed" / "pld_integrado.parquet"
    save_parquet(df_final, destino)

    print("\nDataset integrado salvo em:", destino)

    return df_final


def prepare_pld_d1(dataframe: pd.DataFrame | None = None) -> pd.DataFrame:
    """Adiciona o PLD do próximo dia de calendário para o mesmo submercado.

    A correspondência é feita explicitamente por ``data_alvo`` e submercado,
    sem usar ``shift(-1)``. O resultado é apenas uma preparação inicial: a
    disponibilidade temporal das variáveis ainda deve ser estudada antes do
    treinamento de qualquer modelo.
    """
    raiz = Path(__file__).resolve().parents[3]
    caminho_integrado = raiz / "data" / "processed" / "pld_integrado.parquet"

    if dataframe is None:
        if not caminho_integrado.exists():
            raise FileNotFoundError(
                f"Arquivo não encontrado: {caminho_integrado}. "
                "Execute merge_datasets() primeiro."
            )
        dataframe = pd.read_parquet(caminho_integrado)

    df_treino = dataframe.copy()
    chaves = ["data", "submercado"]
    colunas_necessarias = {*chaves, "pld_medio_dia"}
    validate_input_dataframe(df_treino, colunas_necessarias, "PLD D+1")

    colunas_ja_existentes = {"data_alvo", "pld_d1"}.intersection(
        df_treino.columns
    )

    if colunas_ja_existentes:
        raise ValueError(
            "Colunas do alvo já existentes antes da preparação: "
            + ", ".join(sorted(colunas_ja_existentes))
        )

    validate_no_missing_values(
        df_treino,
        chaves,
        "chaves do dataset integrado",
    )

    if not pd.api.types.is_datetime64_any_dtype(df_treino["data"]):
        raise TypeError("A coluna data não possui tipo de data!")

    if not pd.api.types.is_numeric_dtype(df_treino["pld_medio_dia"]):
        raise TypeError("A coluna pld_medio_dia não possui tipo numérico!")

    validate_unique_keys(df_treino, chaves, "preparação do PLD D+1")

    df_treino["data_alvo"] = df_treino["data"] + pd.Timedelta(days=1)

    alvos = (
        dataframe[["data", "submercado", "pld_medio_dia"]]
        .rename(columns={
            "data": "data_alvo",
            "pld_medio_dia": "pld_d1",
        })
    )

    linhas_antes = len(df_treino)
    df_treino = df_treino.merge(
        alvos,
        on=["data_alvo", "submercado"],
        how="left",
        validate="one_to_one",
    )

    if len(df_treino) != linhas_antes:
        raise ValueError("A criação do PLD D+1 alterou a quantidade de linhas!")

    sem_alvo = df_treino[df_treino["pld_d1"].isna()]
    print("\nRegistros sem PLD no próximo dia de calendário:", len(sem_alvo))
    if not sem_alvo.empty:
        print(
            sem_alvo[["data", "data_alvo", "submercado"]]
            .head(30)
            .to_string(index=False)
        )

    destino = raiz / "data" / "processed" / "pld_treino.parquet"
    save_parquet(df_treino, destino)

    print("\nDataset com alvo D+1 salvo em:", destino)
    print(
        "Aviso: este arquivo ainda não está pronto para treinamento. "
        "É necessário validar quando cada variável estaria disponível."
    )

    return df_treino


def integrate_hourly_datasets(
    pld: pd.DataFrame | None = None,
    balanco: pd.DataFrame | None = None,
    carga: pd.DataFrame | None = None,
    ear: pd.DataFrame | None = None,
    ena: pd.DataFrame | None = None,
    save: bool = True,
) -> pd.DataFrame:
    """Integra fontes horárias e diárias sem criar alvos nem perder PLD.

    Valores ONS do próprio alvo ficam neste arquivo apenas para diagnóstico.
    A engenharia de features consulta novamente as fontes com datas anteriores
    à emissão; ela nunca utiliza diretamente essas colunas contemporâneas.
    """
    root = Path(__file__).resolve().parents[3]
    interim = root / "data" / "interim"
    sources = {
        "PLD horário": pld if pld is not None else pd.read_parquet(interim / "pld_horario.parquet"),
        "Balanço horário": balanco if balanco is not None else pd.read_parquet(interim / "balanco_energia_horario.parquet"),
        "Carga": carga if carga is not None else pd.read_parquet(interim / "carga_energia.parquet"),
        "EAR": ear if ear is not None else pd.read_parquet(interim / "ear.parquet"),
        "ENA": ena if ena is not None else pd.read_parquet(interim / "ena.parquet"),
    }
    hourly_keys = ["instante", "submercado"]
    daily_keys = ["data", "submercado"]
    for name, source in sources.items():
        keys = hourly_keys if "horário" in name else daily_keys
        validate_input_dataframe(source, set(keys), name)
        validate_no_missing_values(source, keys, name)
        validate_unique_keys(source, keys, name)
        if source.columns.duplicated().any():
            raise ValueError(f"{name}: nomes de colunas duplicados")
        time_key = keys[0]
        if not pd.api.types.is_datetime64_any_dtype(source[time_key]):
            raise TypeError(f"{name}: {time_key} precisa ser datetime")
        if name in ("PLD horário", "Balanço horário"):
            if (source["instante"] != source["instante"].dt.floor("h")).any():
                raise ValueError(f"{name}: instante fora do início da hora")
        elif (source["data"] != source["data"].dt.normalize()).any():
            raise ValueError(f"{name}: data contém horário")
        sources[name] = source.copy()
        sources[name]["submercado"] = source["submercado"].astype("string")

    base = sources["PLD horário"]
    validate_input_dataframe(base, {"data", "hora", "pld_horario"}, "PLD horário")
    if not (base["data"] == base["instante"].dt.normalize()).all():
        raise ValueError("PLD horário: data não corresponde a instante")
    if not (base["hora"] == base["instante"].dt.hour).all():
        raise ValueError("PLD horário: hora não corresponde a instante")
    if not pd.api.types.is_datetime64_any_dtype(base["data"]):
        raise TypeError("PLD horário: data precisa ser datetime")

    result = base.copy()
    for name, source in list(sources.items())[1:]:
        keys = hourly_keys if name == "Balanço horário" else daily_keys
        collision = (set(result.columns) & set(source.columns)) - set(keys)
        if collision:
            raise ValueError(f"{name}: colunas conflitantes: {', '.join(sorted(collision))}")
        correspondence = result[keys].drop_duplicates().merge(
            source[keys], on=keys, how="outer", indicator=True,
            validate="one_to_one",
        )
        print(
            f"{name}: left_only={sum(correspondence['_merge'] == 'left_only')}, "
            f"right_only={sum(correspondence['_merge'] == 'right_only')}"
        )
        for status in ("left_only", "right_only"):
            unmatched = correspondence.loc[correspondence["_merge"] == status, keys]
            if not unmatched.empty:
                print(f"{name}, {status}, primeiras chaves:\n{unmatched.head(20).to_string(index=False)}")
        count = len(result)
        result = result.merge(
            source, on=keys, how="left",
            validate="one_to_one" if name == "Balanço horário" else "many_to_one",
        )
        if len(result) != count:
            raise ValueError(f"{name}: merge alterou a quantidade de linhas")

    validate_unique_keys(result, hourly_keys, "PLD horário integrado")
    result = sort_dataframe(result, hourly_keys)
    print("Nulos após integração horária:\n", result.isna().sum())
    if save:
        save_parquet(result, root / "data" / "processed" / "pld_horario_integrado.parquet")
    return result


def prepare_multi_horizon_targets(
    pld: pd.DataFrame | None = None,
    issue_hour: int = 12,
    days_ahead: int = 1,
    first_target_day_offset: int = 1,
    submarkets: list[str] | None = None,
    save: bool = True,
) -> pd.DataFrame:
    """Gera grade longa de alvos e consulta o PLD pela hora de calendário.

    Uma hora não publicada permanece NaN: não deslocamos a série por linha.
    As horas são relógio local de São Paulo, sem fuso no Parquet, de acordo
    com os CSVs originais da CCEE. O fuso é interpretado na validação temporal.
    """
    if not 0 <= issue_hour <= 23:
        raise ValueError("issue_hour deve estar entre 0 e 23")
    if days_ahead < 1 or first_target_day_offset < 0:
        raise ValueError("days_ahead deve ser positivo e o deslocamento não negativo")
    if first_target_day_offset == 0 and issue_hour != 0:
        raise ValueError("Para prever o próprio dia, a emissão deve ocorrer às 00h")

    root = Path(__file__).resolve().parents[3]
    if pld is None:
        pld = pd.read_parquet(root / "data" / "interim" / "pld_horario.parquet")
    validate_input_dataframe(pld, {"instante", "submercado", "pld_horario"}, "PLD horário")
    validate_no_missing_values(pld, ["instante", "submercado", "pld_horario"], "PLD horário")
    validate_unique_keys(pld, ["instante", "submercado"], "PLD horário")
    if not pd.api.types.is_datetime64_any_dtype(pld["instante"]):
        raise TypeError("instante precisa ser datetime")

    first_day = pld["instante"].min().normalize()
    last_day = pld["instante"].max().normalize()
    issue_days = pd.date_range(
        first_day - pd.Timedelta(days=first_target_day_offset),
        last_day - pd.Timedelta(days=first_target_day_offset), freq="D",
    )
    offsets = range(first_target_day_offset, first_target_day_offset + days_ahead)
    markets = sorted(SUBMARKETS) if submarkets is None else sorted(submarkets)
    if not markets or not set(markets).issubset(SUBMARKETS):
        raise ValueError("A grade deve usar submercados conhecidos")
    if not set(pld["submercado"].unique()).issubset(set(markets)):
        raise ValueError("Existem submercados do PLD fora da grade")
    grid = pd.MultiIndex.from_product(
        [issue_days, offsets, range(24), markets],
        names=["issue_day", "target_day_offset", "hora_alvo", "submercado"],
    ).to_frame(index=False)
    grid["issue_time"] = grid["issue_day"] + pd.Timedelta(hours=issue_hour)
    grid["target_time"] = (
        grid["issue_day"]
        + pd.to_timedelta(grid["target_day_offset"], unit="D")
        + pd.to_timedelta(grid["hora_alvo"], unit="h")
    )
    grid["horizon"] = (
        (grid["target_time"] - grid["issue_time"]) / pd.Timedelta(hours=1)
    ).astype("int64")
    if (grid["horizon"] < 0).any():
        raise ValueError("Existem alvos anteriores à emissão")

    lookup = pld[["instante", "submercado", "pld_horario"]].rename(
        columns={"instante": "target_time", "pld_horario": "target_pld"}
    )
    result = grid.merge(
        lookup, on=["target_time", "submercado"], how="left", validate="many_to_one",
    )
    if len(result) != len(grid):
        raise ValueError("A consulta do alvo alterou a grade horária")
    result = result[["issue_time", "target_time", "submercado", "horizon", "target_pld"]]
    validate_unique_keys(result, ["issue_time", "target_time", "submercado"], "alvos horários")
    result = sort_dataframe(result, ["issue_time", "target_time", "submercado"])
    print("Alvos horários ausentes na publicação:", result["target_pld"].isna().sum())
    if save:
        save_parquet(result, root / "data" / "processed" / "pld_horario_alvos.parquet")
    return result


if __name__ == "__main__":
    dados_integrados = merge_datasets()
    prepare_pld_d1(dados_integrados)
