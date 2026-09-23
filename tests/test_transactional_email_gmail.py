"""Gmail-safe BlinQ transactional mail remains usable with images disabled."""
from types import SimpleNamespace

from tbt.services import auth_email


def _config():
    return SimpleNamespace(
        blinq_smtp_host="smtp.example.test",
        blinq_smtp_port=587,
        blinq_smtp_from="BlinQ <security@example.test>",
        blinq_smtp_username="security@example.test",
        blinq_smtp_password="test-only",
        blinq_smtp_starttls=True,
    )


class FakeSMTP:
    delivered = []

    def __init__(self, host, port, **kwargs):
        assert host == "smtp.example.test"
        assert port == 587

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def ehlo(self):
        pass

    def starttls(self, **kwargs):
        pass

    def login(self, username, password):
        assert username == "security@example.test"
        assert password == "test-only"

    def send_message(self, msg):
        self.delivered.append(msg)


def _assert_gmail_safe(msg):
    assert msg.get_content_type() == "multipart/alternative"
    assert not list(msg.iter_attachments())
    assert all(not part.get_content_type().startswith("image/") for part in msg.walk())
    plain = msg.get_body(preferencelist=("plain",)).get_content()
    html = msg.get_body(preferencelist=("html",)).get_content()
    assert "Blin" in html and "color:#43e6a0" in html
    assert "<img" not in html and "cid:" not in html
    assert "blinq.png" not in str(msg)
    assert msg["Date"] and msg["Date"].endswith("+0000")
    assert msg["Message-ID"] and msg["Message-ID"].endswith("@example.test>")
    assert msg["Auto-Submitted"] == "auto-generated"
    return plain, html


def test_action_email_gmail_uses_visible_text_brand_without_cid(monkeypatch):
    FakeSMTP.delivered = []
    monkeypatch.setattr(auth_email.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(
        auth_email, "_firebase_action_link",
        lambda _cfg, kind, _email: f"https://blinq.example/auth/action?mode={kind}&oobCode=fake",
    )
    assert auth_email.send_blinq_action_email(
        _config(), "member@example.test", "reset"
    ) is True
    assert len(FakeSMTP.delivered) == 1
    msg = FakeSMTP.delivered[0]
    plain, html = _assert_gmail_safe(msg)
    assert "Obnovte svoje heslo" in plain
    assert "Reset your password" in html
    assert "https://blinq.example/auth/action?mode=reset" in plain
    assert "&amp;oobCode=fake" in html
    assert msg["From"] == "BlinQ <security@example.test>"


def test_lifecycle_email_uses_same_image_free_template(monkeypatch):
    FakeSMTP.delivered = []
    monkeypatch.setattr(auth_email.smtplib, "SMTP", FakeSMTP)
    sent = auth_email.send_blinq_transactional_email(
        _config(),
        "member@example.test",
        subject="BlinQ membership",
        eyebrow="BLINQ MEMBERSHIP",
        title_sk="Predplatné sa končí",
        body_sk="Účet prejde na ROOKIE.",
        title_en="Subscription expires",
        body_en="Your account returns to ROOKIE.",
        button_label="Otvoriť BlinQ / Open BlinQ",
        button_url="https://blinq.example/account",
    )
    assert sent is True
    assert len(FakeSMTP.delivered) == 1
    plain, html = _assert_gmail_safe(FakeSMTP.delivered[0])
    assert "Účet prejde na ROOKIE" in plain
    assert "Subscription expires" in html
    assert 'href="https://blinq.example/account"' in html


def test_text_brand_remains_present_when_all_images_blocked():
    plain, html = auth_email.render_blinq_email(
        eyebrow="BLINQ INTELLIGENCE",
        title_sk="Overte svoj e-mail",
        body_sk="Overenie účtu.",
        title_en="Verify your email",
        body_en="Verify your account.",
        button_label="Overiť / Verify",
        button_url="https://blinq.example/auth/action?mode=verifyEmail",
    )
    assert "Overte svoj e-mail" in plain
    assert "Verify your email" in plain
    assert "Blin<span" in html
    assert "cid:" not in html


def test_transactional_mail_requires_valid_sender_mailbox():
    import pytest

    cfg = _config()
    cfg.blinq_smtp_from = "BlinQ"
    with pytest.raises(ValueError, match="BLINQ_SMTP_FROM"):
        auth_email._build_transactional_message(
            cfg, "member@example.test", "Subject", "Plain body", "<p>HTML body</p>"
        )
