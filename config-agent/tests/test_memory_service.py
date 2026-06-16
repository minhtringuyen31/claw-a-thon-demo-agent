from services.memory_service import MockMemoryService


def test_get_returns_none_when_missing():
    svc = MockMemoryService()
    assert svc.get("session:abc") is None


def test_set_and_get():
    svc = MockMemoryService()
    svc.set("prefs:global", {"default_action": "REJECT"})
    result = svc.get("prefs:global")
    assert result == {"default_action": "REJECT"}


def test_set_overwrites():
    svc = MockMemoryService()
    svc.set("prefs:global", {"default_action": "REJECT"})
    svc.set("prefs:global", {"default_action": "REVIEW"})
    assert svc.get("prefs:global")["default_action"] == "REVIEW"


def test_append_creates_list():
    svc = MockMemoryService()
    svc.append("session:abc", {"input": "test1"})
    svc.append("session:abc", {"input": "test2"})
    result = svc.get("session:abc")
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["input"] == "test1"
