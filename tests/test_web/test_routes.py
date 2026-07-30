"""Tests for the server-rendered frontend pages."""

from pathlib import Path

from bs4 import BeautifulSoup

import app as app_package
from app._version import __version__
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


def test_app_exposes_current_development_version_without_release_url(flask_app):
    globals_ = flask_app.jinja_env.globals

    assert globals_["show_version"] is True
    assert globals_["app_version"] == __version__
    assert globals_["release_url"] is None


def test_development_versions_do_not_link_to_releases():
    assert app_package._release_url_for("0.2.0.dev1") is None
    assert app_package._release_url_for("0.2.0+local") is None


def test_stable_versions_link_to_the_matching_release():
    assert app_package._release_url_for("0.2.0") == (
        "https://github.com/dead-plant/ThePhish-NG/releases/tag/v0.2.0"
    )


def test_index_renders_linked_version_footer(client, flask_app, monkeypatch):
    _set_webapp_links(monkeypatch)
    monkeypatch.setitem(flask_app.jinja_env.globals, "app_version", "0.2.0")
    monkeypatch.setitem(
        flask_app.jinja_env.globals,
        "release_url",
        "https://github.com/dead-plant/ThePhish-NG/releases/tag/v0.2.0",
    )

    response = client.get("/")

    assert response.status_code == 200
    page = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    footer = page.select_one("[data-app-version]")
    assert footer is not None
    assert footer.get_text(" ", strip=True) == "ThePhish-NG v0.2.0"
    release_link = footer.select_one("a")
    assert release_link is not None
    assert release_link.get_text(strip=True) == "v0.2.0"
    assert release_link["href"] == (
        "https://github.com/dead-plant/ThePhish-NG/releases/tag/v0.2.0"
    )


def test_index_renders_unlinked_development_version(
    client, flask_app, monkeypatch
):
    _set_webapp_links(monkeypatch)
    monkeypatch.setitem(flask_app.jinja_env.globals, "release_url", None)

    response = client.get("/")

    page = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    footer = page.select_one("[data-app-version]")
    assert footer is not None
    assert footer.get_text(" ", strip=True) == f"ThePhish-NG v{__version__}"
    assert footer.select_one("a") is None


def test_app_omits_version_footer_when_configured_off(monkeypatch):
    monkeypatch.setitem(
        web_routes.config.get_app_config()["webapp"],
        "show_version",
        False,
    )
    flask_app = app_package.create_app()
    flask_app.config["TESTING"] = True

    assert flask_app.jinja_env.globals["show_version"] is False
    response = flask_app.test_client().get("/")

    page = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    assert page.select_one("[data-app-version]") is None


def test_analysis_page_renders_layout_and_configured_links(client, monkeypatch):
    _set_webapp_links(monkeypatch)

    response = client.get("/analysis/aid123")

    assert response.status_code == 200
    page = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    assert page.body["data-analysis-id"] == "aid123"
    assert page.select_one("#analysisStatus").get_text() == "Loading analysis…"
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


def test_analysis_page_renders_hidden_thehive_case_action(client, monkeypatch):
    _set_webapp_links(monkeypatch)

    response = client.get("/analysis/aid123")

    assert response.status_code == 200
    page = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    actions = page.select_one(".analysis-actions")
    assert actions is not None
    case_link = actions.select_one("#analysisCaseLink")
    assert actions.select_one('a.analysis-back-link[href="/"]') is not None
    assert case_link is not None
    assert "d-none" in case_link.get("class", [])
    assert case_link["data-thehive-base-url"] == "https://thehive.example.test"
    assert case_link["target"] == "_blank"
    assert set(case_link["rel"]) == {"noopener", "noreferrer"}
    assert case_link.select_one("#analysisCaseLinkText").get_text(strip=True) == "Open TheHive case"


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


def test_analysis_page_loads_analysis_controller(client, monkeypatch):
    _set_webapp_links(monkeypatch)

    response = client.get("/analysis/aid123")

    page = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    script = page.select_one('script[src$="/static/assets/js/analysis.js"]')
    assert script is not None

