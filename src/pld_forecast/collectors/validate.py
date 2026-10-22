"""Funções de validação dos CSVs baixados."""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd


def _read_csv(path: Path) -> tuple[pd.DataFrame, str, str]:
    """Detecta encoding e separador antes de ler o CSV com Pandas."""
    raw_sample = path.read_bytes()[:65536]
    if not raw_sample:
        raise ValueError("arquivo vazio")

    lowered = raw_sample.lstrip().lower()
    if lowered.startswith((b"<html", b"<!doctype html")):
        raise ValueError("conteúdo HTML disfarçado de CSV")
    if lowered.startswith((b"{", b"[")):
        raise ValueError("conteúdo JSON disfarçado de CSV")

    for encoding in ("utf-8-sig", "utf-8", "iso-8859-2", "cp1252", "latin-1"):
        try:
            text_sample = raw_sample.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("encoding não reconhecido")

    try:
        separator = csv.Sniffer().sniff(text_sample, delimiters=";,\t|").delimiter
    except csv.Error as error:
        raise ValueError("separador CSV não reconhecido") from error

    try:
        dataframe = pd.read_csv(
            path,
            sep=separator,
            encoding=encoding,
            dtype=str,
            low_memory=False,
        )
    except Exception as error:
        raise ValueError(f"erro grave de leitura CSV: {error}") from error

    return dataframe, encoding, separator


def validate_csv(path: Path) -> dict:
    """Valida qualquer CSV. Erros bloqueiam a substituição; avisos não bloqueiam."""
    path = Path(path)
    if not path.is_file():
        return {
            "valid": False,
            "errors": ["arquivo inexistente"],
            "warnings": [],
            "flags": [],
        }

    try:
        dataframe, encoding, separator = _read_csv(path)
    except (OSError, ValueError) as error:
        return {
            "valid": False,
            "errors": [str(error)],
            "warnings": [],
            "flags": [],
        }

    errors = []
    warnings = []
    if len(dataframe.columns) < 2:
        errors.append("CSV possui menos de duas colunas")
    if dataframe.empty:
        errors.append("CSV não possui linhas de dados")
    if any(not str(column).strip() for column in dataframe.columns):
        errors.append("cabeçalho ausente ou inválido")
    if dataframe.dropna(how="all").shape[0] != dataframe.shape[0]:
        warnings.append("existem linhas completamente vazias")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "flags": [],
        "rows": len(dataframe),
        "columns": len(dataframe.columns),
        "encoding": encoding,
        "separator": separator,
    }


def validate_pld_media_diaria(path: Path) -> dict:
    """Adiciona as regras específicas do CSV de PLD médio diário."""
    result = validate_csv(path)
    if not result["valid"]:
        return result

    dataframe, _, _ = _read_csv(Path(path))
    required_columns = {"MES_REFERENCIA", "SUBMERCADO", "DIA", "PLD_MEDIA_DIA"}
    missing_columns = sorted(required_columns - set(dataframe.columns))
    if missing_columns:
        result["errors"].append(
            "colunas obrigatórias ausentes: " + ", ".join(missing_columns)
        )
        result["valid"] = False
        return result

    required_data = dataframe[list(required_columns)].fillna("")
    missing_values = int(
        required_data.apply(lambda column: column.str.strip() == "").sum().sum()
    )
    if missing_values:
        result["errors"].append(f"{missing_values} valor(es) obrigatório(s) ausente(s)")

    dates = pd.to_datetime(dataframe["DIA"], dayfirst=True, errors="coerce")
    invalid_dates = int(dates.isna().sum())
    if invalid_dates:
        result["errors"].append(f"{invalid_dates} data(s) inválida(s)")

    prices = pd.to_numeric(
        dataframe["PLD_MEDIA_DIA"].str.replace(",", ".", regex=False),
        errors="coerce",
    )
    invalid_prices = int(prices.isna().sum())
    if invalid_prices:
        result["errors"].append(f"{invalid_prices} valor(es) de PLD não numérico(s)")
    if (prices < 0).any():
        result["warnings"].append("existem valores negativos de PLD; nenhum valor foi removido")

    valid_markets = {"NORTE", "NORDESTE", "SUDESTE", "SUL"}
    markets = set(dataframe["SUBMERCADO"].dropna().str.strip().str.upper())
    unknown_markets = sorted(markets - valid_markets)
    if unknown_markets:
        result["errors"].append(
            "submercados não reconhecidos: " + ", ".join(unknown_markets)
        )

    duplicate_mask = dataframe.duplicated(
        subset=["DIA", "SUBMERCADO"], keep=False
    )
    duplicate_rows = int(duplicate_mask.sum())
    if duplicate_rows:
        duplicated_data = dataframe.loc[duplicate_mask]
        grouped_duplicates = duplicated_data.groupby(
            ["DIA", "SUBMERCADO"], dropna=False
        )
        duplicate_groups = grouped_duplicates.ngroups
        excess_rows = duplicate_rows - duplicate_groups

        # Uma chave repetida com valores diferentes é ambígua e continua
        # sendo fatal. Apenas cópias totalmente idênticas viram aviso.
        conflicting_groups = sum(
            len(group.drop_duplicates()) > 1
            for _, group in grouped_duplicates
        )
        if conflicting_groups:
            result["errors"].append(
                f"{conflicting_groups} chave(s) DIA + SUBMERCADO possuem "
                "registros duplicados com valores diferentes"
            )
        else:
            # As linhas não são removidas do arquivo bruto. A flag também será
            # usada pelo cliente para deixar o aviso visível no nome do arquivo.
            result["flags"].append("duplicate_rows")
            result["duplicate_rows"] = duplicate_rows
            result["duplicate_groups"] = duplicate_groups
            result["duplicate_excess_rows"] = excess_rows
            result["warnings"].append(
                f"{duplicate_rows} linha(s) pertencem a {duplicate_groups} chave(s) "
                f"DIA + SUBMERCADO duplicada(s), com {excess_rows} cópia(s) "
                "excedente(s); o arquivo bruto foi preservado sem alterações"
            )

    reference_month = dataframe["MES_REFERENCIA"].astype(str).str.replace(
        r"\.0$", "", regex=True
    )
    expected_month = dates.dt.strftime("%Y%m")
    inconsistent_months = int(
        ((reference_month != expected_month) & dates.notna()).sum()
    )
    if inconsistent_months:
        result["errors"].append(
            f"{inconsistent_months} linha(s) com MES_REFERENCIA incompatível com DIA"
        )

    if dates.notna().any():
        market_count = dataframe.assign(_date=dates).groupby("_date")["SUBMERCADO"].nunique()
        incomplete_days = int((market_count < 4).sum())
        if incomplete_days:
            result["warnings"].append(
                f"{incomplete_days} dia(s) possuem menos de quatro submercados"
            )

        complete_period = pd.date_range(dates.min(), dates.max(), freq="D")
        observed_days = pd.DatetimeIndex(dates.dropna().unique())
        absent_days = len(complete_period.difference(observed_days))
        if absent_days:
            result["warnings"].append(
                f"{absent_days} dia(s) ausente(s) no intervalo do arquivo"
            )

    result["valid"] = not result["errors"]
    return result


def parse_pld_hourly_reference(dataframe: pd.DataFrame) -> pd.Series:
    """Constrói o instante horário da CCEE sem depender da ordem das linhas.

    A coluna DIA já apareceu tanto como dia do mês quanto como DD/MM/AAAA.
    MES_REFERENCIA permite interpretar o primeiro formato sem ambiguidade.
    """
    month_text = dataframe["MES_REFERENCIA"].astype("string").str.strip()
    if not month_text.str.fullmatch(r"\d{6}").all():
        raise ValueError("MES_REFERENCIA deve estar em AAAAMM")
    pd.to_datetime(month_text, format="%Y%m", errors="raise")

    day_text = dataframe["DIA"].astype("string").str.strip()
    short_day = day_text.str.fullmatch(r"\d{1,2}")
    full_date = day_text.str.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}")
    if not (short_day | full_date).all():
        raise ValueError("DIA deve ser dia do mês ou DD/MM/AAAA")

    dates = pd.Series(pd.NaT, index=dataframe.index, dtype="datetime64[ns]")
    if short_day.any():
        date_text = month_text.loc[short_day] + day_text.loc[short_day].str.zfill(2)
        dates.loc[short_day] = pd.to_datetime(date_text, format="%Y%m%d", errors="raise")
    if full_date.any():
        dates.loc[full_date] = pd.to_datetime(
            day_text.loc[full_date], format="%d/%m/%Y", errors="raise"
        )
    if not (dates.dt.strftime("%Y%m") == month_text).all():
        raise ValueError("MES_REFERENCIA incompatível com DIA")

    hours = pd.to_numeric(dataframe["HORA"], errors="raise")
    if hours.isna().any() or not ((hours >= 0) & (hours <= 23) & (hours % 1 == 0)).all():
        raise ValueError("HORA deve ser um inteiro entre 0 e 23")
    return dates + pd.to_timedelta(hours.astype(int), unit="h")


def validate_pld_horario(path: Path) -> dict:
    """Valida o PLD horário e relata lacunas sem modificar o arquivo bruto."""
    result = validate_csv(path)
    if not result["valid"]:
        return result

    dataframe, _, _ = _read_csv(Path(path))
    required = {
        "MES_REFERENCIA", "SUBMERCADO", "PERIODO_COMERCIALIZACAO",
        "DIA", "HORA", "PLD_HORA",
    }
    missing = sorted(required - set(dataframe.columns))
    if missing:
        result["errors"].append("colunas obrigatórias ausentes: " + ", ".join(missing))
        result["valid"] = False
        return result

    required_data = dataframe[list(required)].fillna("")
    absent = int(required_data.apply(lambda column: column.str.strip() == "").sum().sum())
    if absent:
        result["errors"].append(f"{absent} valor(es) obrigatório(s) ausente(s)")
        result["valid"] = False
        return result

    markets = dataframe["SUBMERCADO"].astype("string").str.strip().str.upper()
    unknown = sorted(set(markets) - {"NORTE", "NORDESTE", "SUDESTE", "SUL"})
    if unknown:
        result["errors"].append("submercados não reconhecidos: " + ", ".join(unknown))

    try:
        instants = parse_pld_hourly_reference(dataframe)
    except (TypeError, ValueError) as error:
        result["errors"].append(str(error))
        result["valid"] = False
        return result

    try:
        periods = pd.to_numeric(dataframe["PERIODO_COMERCIALIZACAO"], errors="raise")
        if not ((periods > 0) & (periods % 1 == 0)).all():
            result["errors"].append("PERIODO_COMERCIALIZACAO deve ser inteiro positivo")
        prices = pd.to_numeric(
            dataframe["PLD_HORA"].str.replace(",", ".", regex=False),
            errors="raise",
        )
        if prices.isna().any():
            result["errors"].append("Existem valores de PLD_HORA ausentes")
        if (prices < 0).any():
            result["warnings"].append("Existem preços negativos; nenhum valor foi alterado")
    except (TypeError, ValueError) as error:
        result["errors"].append(f"Valor numérico inválido: {error}")

    keyed = dataframe.assign(_instante=instants, _submercado=markets)
    duplicated = keyed.duplicated(subset=["_instante", "_submercado"], keep=False)
    if duplicated.any():
        grouped = keyed.loc[duplicated].groupby(["_instante", "_submercado"])
        conflict_count = sum(
            len(group[dataframe.columns].drop_duplicates()) > 1
            for _, group in grouped
        )
        if conflict_count:
            result["errors"].append(
                f"{conflict_count} chave(s) instante + submercado com valores diferentes"
            )
        else:
            result["flags"].append("duplicate_rows")
            result["duplicate_rows"] = int(duplicated.sum())
            result["duplicate_groups"] = grouped.ngroups
            result["duplicate_excess_rows"] = int(duplicated.sum()) - grouped.ngroups
            result["warnings"].append(
                f"{result['duplicate_excess_rows']} cópia(s) horária(s) idêntica(s); bruto preservado"
            )

    # Contamos chaves únicas para não confundir duplicata com hora presente.
    unique_keys = keyed[["_instante", "_submercado"]].drop_duplicates()
    expected_hours = pd.date_range(instants.min(), instants.max(), freq="h")
    expected_count = len(expected_hours) * 4
    absent_keys = expected_count - len(unique_keys)
    if absent_keys:
        result["warnings"].append(
            f"{absent_keys} chave(s) horário + submercado ausente(s) no intervalo do arquivo"
        )
        result["missing_hourly_keys"] = absent_keys

    result["max_reference_time"] = instants.max().isoformat()
    result["valid"] = not result["errors"]
    return result
