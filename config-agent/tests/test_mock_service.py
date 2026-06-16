from services.mock_config_service import MockConfigService


def test_get_profile_returns_none_when_not_exists():
    svc = MockConfigService()
    assert svc.get_profile("app_999") is None


def test_save_and_get_profile():
    svc = MockConfigService()
    profile = {"name": "Test Profile", "version": 1}
    saved = svc.save_profile("app_1", profile)
    assert saved["app_id"] == "app_1"
    assert saved["name"] == "Test Profile"
    assert "saved_at" in saved
    retrieved = svc.get_profile("app_1")
    assert retrieved == saved


def test_save_overwrites_existing():
    svc = MockConfigService()
    svc.save_profile("app_1", {"name": "Old"})
    svc.save_profile("app_1", {"name": "New"})
    result = svc.get_profile("app_1")
    assert result["name"] == "New"


def test_get_all_profiles():
    svc = MockConfigService()
    svc.save_profile("app_1", {"name": "A"})
    svc.save_profile("app_2", {"name": "B"})
    all_profiles = svc.get_all_profiles()
    assert len(all_profiles) == 2
    names = {p["name"] for p in all_profiles}
    assert names == {"A", "B"}
