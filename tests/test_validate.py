from pathlib import Path

from src.data.validate import validate_csv, validate_pld_media_diaria


def write(path: Path, content: str, encoding: str = "utf-8") -> Path:
    path.write_text(content, encoding=encoding)
    return path


def test_missing_and_disguised_files_are_invalid(tmp_path):
    assert not validate_csv(tmp_path / "missing.csv")["valid"]
    assert not validate_csv(write(tmp_path / "html.csv", "<html>erro</html>"))["valid"]
    assert not validate_csv(write(tmp_path / "json.csv", '{"error": true}'))["valid"]


def test_general_csv_detects_separator_and_encoding(tmp_path):
    path = write(tmp_path / "valid.csv", "nome;valor\nA;1\n", "iso-8859-2")
    result = validate_csv(path)
    assert result["valid"]
    assert result["separator"] == ";"
    assert result["rows"] == 1 and result["columns"] == 2


def test_pld_real_schema_is_valid(tmp_path):
    rows = [
        '"MES_REFERENCIA";"SUBMERCADO";"DIA";"PLD_MEDIA_DIA"',
        '"202601";NORTE;"01/01/2026";100.1',
        '"202601";NORDESTE;"01/01/2026";100.2',
        '"202601";SUDESTE;"01/01/2026";100.3',
        '"202601";SUL;"01/01/2026";100.4',
    ]
    result = validate_pld_media_diaria(write(tmp_path / "pld.csv", "\n".join(rows)))
    assert result["valid"], result["errors"]


def test_pld_schema_finds_fatal_semantic_errors(tmp_path):
    content = (
        "MES_REFERENCIA;SUBMERCADO;DIA;PLD_MEDIA_DIA\n"
        "202602;INVALIDO;31/01/2026;abc\n"
        "202602;INVALIDO;31/01/2026;abc\n"
    )
    result = validate_pld_media_diaria(write(tmp_path / "bad.csv", content))
    assert not result["valid"]
    assert any("não numérico" in error for error in result["errors"])
    assert any("submercados" in error for error in result["errors"])
    assert any("MES_REFERENCIA" in error for error in result["errors"])
    assert "duplicate_rows" in result["flags"]
    assert any("duplicada" in warning for warning in result["warnings"])


def test_identical_pld_duplicates_are_warning_not_fatal(tmp_path):
    content = (
        "MES_REFERENCIA;SUBMERCADO;DIA;PLD_MEDIA_DIA\n"
        "202601;NORTE;01/01/2026;100.00\n"
        "202601;NORTE;01/01/2026;100.00\n"
    )
    result = validate_pld_media_diaria(write(tmp_path / "duplicates.csv", content))

    assert result["valid"]
    assert result["duplicate_rows"] == 2
    assert result["duplicate_groups"] == 1
    assert result["duplicate_excess_rows"] == 1
    assert "duplicate_rows" in result["flags"]


def test_conflicting_pld_duplicates_remain_fatal(tmp_path):
    content = (
        "MES_REFERENCIA;SUBMERCADO;DIA;PLD_MEDIA_DIA\n"
        "202601;NORTE;01/01/2026;100.00\n"
        "202601;NORTE;01/01/2026;200.00\n"
    )
    result = validate_pld_media_diaria(write(tmp_path / "conflict.csv", content))

    assert not result["valid"]
    assert any("valores diferentes" in error for error in result["errors"])
    assert "duplicate_rows" not in result["flags"]
