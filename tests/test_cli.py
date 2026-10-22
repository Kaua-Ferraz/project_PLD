import pytest

from src.pld_forecast import cli


def test_cli_expoe_comandos_e_encaminha_snapshot(tmp_path, monkeypatch):
    commands = {
        "collect", "transform", "integrate", "features",
        "backtest", "forecast", "evaluate",
    }
    for command in commands:
        assert cli.build_parser().parse_args([command]).command == command
    settings = cli.build_parser().parse_args([
        "integrate", "--issue-hour", "0", "--days-ahead", "3",
        "--first-target-day-offset", "0",
    ])
    assert (settings.issue_hour, settings.days_ahead, settings.first_target_day_offset) == (0, 3, 0)

    received = []

    def fake_ccee(**options):
        received.append(options)
        return [{"status": "downloaded"}]

    monkeypatch.setattr(cli, "update_ccee", fake_ccee)
    monkeypatch.setattr(
        cli, "update_ons", lambda **_options: pytest.fail("ONS não deveria ser consultado")
    )

    status = cli.main([
        "collect", "historical", "--portal", "ccee", "--snapshot",
        "--data-dir", str(tmp_path),
    ])
    assert status == 0
    assert received[0]["mode"] == "historical"
    assert received[0]["snapshot_dir"].is_dir()


def test_comandos_futuros_respondem_sem_executar_modelagem():
    with pytest.raises(SystemExit) as error:
        cli.main(["backtest"])
    assert error.value.code == 2
