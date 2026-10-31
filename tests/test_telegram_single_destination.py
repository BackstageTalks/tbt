import json
from pathlib import Path
from types import SimpleNamespace
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import telegram_offer_publisher as tg

def test_single_bot_single_channel_for_all_audiences(tmp_path, monkeypatch):
    monkeypatch.setenv("TGB", "test-token")
    monkeypatch.setenv("TGCH", "-100123456")
    monkeypatch.delenv("TGCH_ELITE", raising=False)
    monkeypatch.delenv("TGCH_FREE", raising=False)
    (tmp_path / "ready").write_text("test")
    tg.save(tmp_path / "messages.json", [
        {"audience": "premium", "text": "offer"},
        {"audience": "free", "text": "free"},
        {"audience": "elite", "text": "results"},
    ])
    seen = []
    class Reply:
        def __init__(self, number): self.number = number
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, *_): return json.dumps({"ok": True, "result": {"message_id": self.number}}).encode()
    def fake_open(request, timeout):
        from urllib.parse import parse_qs
        data = parse_qs(request.data.decode())
        seen.append(data)
        return Reply(len(seen))
    monkeypatch.setattr(tg.urllib.request, "urlopen", fake_open)
    tg.send(SimpleNamespace(output=str(tmp_path)))
    assert len(seen) == 3
    assert {item["chat_id"][0] for item in seen} == {"-100123456"}
    assert tg.load(tmp_path / "receipt.json") == [1, 2, 3]
