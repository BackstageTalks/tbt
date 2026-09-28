from email import policy
from email.parser import BytesParser
from types import SimpleNamespace

from tbt.services.auth_email import _build_transactional_message, render_blinq_email


def cfg():
    return SimpleNamespace(blinq_smtp_from="BlinQ <noreply@blinq.example>")


def test_gmail_safe_transactional_html_and_plain_fallback():
    plain, html = render_blinq_email(
        eyebrow="BLINQ",
        title_sk="Overte svoj e-mail",
        body_sk="Dokončite registráciu.",
        title_en="Verify your email",
        body_en="Complete registration.",
        button_label="Overiť / Verify",
        button_url="https://blinq.example/auth/action?mode=verify&oobCode=abc",
        footer_sk="Túto správu môžete ignorovať.",
        footer_en="You can ignore this message.",
    )
    assert "Overte svoj e-mail" in plain
    assert "https://blinq.example/auth/action" in plain
    assert 'display:none!important' in html
    assert 'bgcolor="#020c0b"' in html
    assert 'bgcolor="#061713"' in html
    assert 'bgcolor="#43e6a0"' in html
    assert '<table role="presentation"' in html
    assert '<img' not in html.lower()
    assert "javascript:" not in html.lower()


def test_transactional_message_is_multipart_with_sender_domain_message_id():
    plain, html = render_blinq_email(
        eyebrow="BLINQ",
        title_sk="Test",
        body_sk="SK",
        title_en="Test EN",
        body_en="EN",
    )
    msg = _build_transactional_message(
        cfg(), "member@example.org", "BlinQ test", plain, html
    )
    parsed = BytesParser(policy=policy.default).parsebytes(msg.as_bytes())
    assert parsed["From"] == "BlinQ <noreply@blinq.example>"
    assert parsed["To"] == "member@example.org"
    assert parsed["Message-ID"].endswith("@blinq.example>")
    assert parsed["Date"]
    assert parsed["Auto-Submitted"] == "auto-generated"
    assert parsed.is_multipart()
    parts = parsed.get_payload()
    assert parts[0].get_content_type() == "text/plain"
    assert parts[1].get_content_type() == "text/html"
