"""Tests for TheHive repository request payloads."""

from app.repositories import thehive


def test_link_url_sends_external_link_payload(monkeypatch):
    calls = []
    monkeypatch.setattr(
        thehive._client.case,
        "link_url",
        lambda case_id, fields: calls.append((case_id, fields)),
    )

    thehive.link_url(
        case_id="case1",
        link_type="ThePhish-NG Analysis",
        url="https://thephish.example.com/analysis/aid123",
    )

    assert calls == [
        (
            "case1",
            {
                "type": "ThePhish-NG Analysis",
                "url": "https://thephish.example.com/analysis/aid123",
            },
        )
    ]
