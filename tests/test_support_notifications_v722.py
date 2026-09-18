from tbt.services import support_notifications as sn


def test_support_notification_is_disabled_without_env(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("BLINQ_SUPPORT_TO_EMAIL", raising=False)
    assert sn.notify_support_ticket({"ticket_id": "BLQ-1"})["reason"] == "not_configured"


def test_support_notification_uses_reply_to(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "key")
    monkeypatch.setenv("BLINQ_SUPPORT_TO_EMAIL", "support@example.com")
    captured = {}
    class Response:
        content = b'{}'
        def raise_for_status(self): pass
        def json(self): return {"id": "msg_1"}
    def fake_post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return Response()
    monkeypatch.setattr(sn.httpx, "post", fake_post)
    result = sn.notify_support_ticket({"ticket_id":"BLQ-1","email":"user@example.com","category":"technical","message":"hello world"})
    assert result["sent"] is True
    assert captured["json"]["reply_to"] == "user@example.com"
    assert captured["headers"]["Idempotency-Key"] == "support-ticket/BLQ-1"
