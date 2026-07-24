"""Tests for the server-rendered frontend pages."""

from pathlib import Path

from bs4 import BeautifulSoup

from app.web import routes as web_routes


def _set_webapp_links(monkeypatch):
    monkeypatch.setattr(
        web_routes.config,
        "get_app_config",
        lambda: {
            "webapp": {
                "thehive_url": "https://thehive.example.test",
                "cortex_url": "https://cortex.example.test",
                "misp_url": "https://misp.example.test",
            }
        },
    )


def test_analysis_page_renders_layout_and_configured_links(client, monkeypatch):
    _set_webapp_links(monkeypatch)

    response = client.get("/analysis/aid123")

    assert response.status_code == 200
    page = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    assert page.body["data-analysis-id"] == "aid123"
    assert page.select_one("#analysisStatus") is not None
    assert page.select_one("#analysisAlert") is not None
    assert page.select_one("#analysisLog") is not None
    assert page.select_one("#analysisLogEntries") is not None
    assert page.select_one("#analysisResult") is not None
    assert page.select_one("#analysisResultTitle") is not None
    assert page.select_one("#analysisResultMessage") is not None
    assert page.select_one('link[href$="/static/assets/css/analysis.css"]') is not None
    assert page.select_one('img.analysis-logo[src$="/static/assets/img/ThePhish_logo.png"]') is not None
    assert {link.get("href") for link in page.select("nav a")} >= {
        "/",
        "https://thehive.example.test",
        "https://cortex.example.test",
        "https://misp.example.test",
    }


def test_analysis_page_escapes_analysis_id(client, monkeypatch):
    _set_webapp_links(monkeypatch)
    injected_id = '<img src=x onerror="alert(1)">'

    response = client.get("/analysis/%3Cimg%20src=x%20onerror=%22alert(1)%22%3E")

    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert injected_id not in text
    page = BeautifulSoup(text, "html.parser")
    assert page.body["data-analysis-id"] == injected_id


def test_analysis_stylesheet_is_served(client):
    response = client.get("/static/assets/css/analysis.css")

    assert response.status_code == 200
    assert response.mimetype == "text/css"


def test_analysis_template_does_not_depend_on_socket_io():
    template = Path("app/web/templates/analysis.html").read_text(encoding="utf-8")

    assert "socket.io" not in template.lower()


def test_index_is_listing_only_and_does_not_require_socket_io(client, monkeypatch):
    _set_webapp_links(monkeypatch)

    response = client.get("/")

    assert response.status_code == 200
    page = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    assert page.select_one("#listMailsBtn") is not None
    assert "disabled" not in page.select_one("#listMailsBtn").get("class", [])
    assert page.select_one("#dataTable") is not None
    assert page.select_one("#logText") is None
    assert page.select_one("#divResult") is None
    assert page.select_one("#goBackLink") is None
    assert not any("socket.io" in (script.get("src") or "").lower() for script in page.select("script"))


def test_index_application_script_contains_no_xhr():
    script = Path("app/web/static/assets/js/thephish.js").read_text(encoding="utf-8")

    assert "XMLHttpRequest" not in script
    assert "window.fetch.bind(window)" in script
