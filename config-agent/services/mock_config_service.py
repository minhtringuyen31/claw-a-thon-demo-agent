from datetime import datetime, timezone


class MockConfigService:
    def __init__(self):
        self._store: dict[str, dict] = {}

    def get_profile(self, app_id: str) -> dict | None:
        return self._store.get(app_id)

    def save_profile(self, app_id: str, profile: dict) -> dict:
        record = {**profile, "app_id": app_id, "saved_at": datetime.now(timezone.utc).isoformat()}
        self._store[app_id] = record
        return record

    def get_all_profiles(self) -> list[dict]:
        return list(self._store.values())
