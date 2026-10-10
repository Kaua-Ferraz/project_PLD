from datetime import datetime

from src.data.ccee import get_resource_year, select_resources


def item(name, format="CSV"):
    return {"id": name, "name": name, "url": f"https://example/{name}", "format": format}


def test_historical_selects_csv_since_2021_and_unknown_year():
    selected = select_resources([item("data-2020"), item("data-2021"), item("accumulated"), item("data-2022", "PDF")], "historical", 2021)
    assert [entry["name"] for entry in selected] == ["data-2021", "accumulated"]


def test_daily_selects_current_year_and_accumulated():
    year = datetime.now().year
    selected = select_resources([item(f"data-{year}"), item(f"data-{year - 1}"), item("accumulated")], "daily", 2021)
    assert [entry["name"] for entry in selected] == [f"data-{year}", "accumulated"]
    assert get_resource_year(item(f"data-{year}")) == year
