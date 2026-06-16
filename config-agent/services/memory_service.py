class MockMemoryService:
    def __init__(self):
        self._store: dict = {}

    def get(self, key: str):
        return self._store.get(key)

    def set(self, key: str, value) -> None:
        self._store[key] = value

    def append(self, key: str, item: dict) -> None:
        existing = self._store.get(key)
        if isinstance(existing, list):
            existing.append(item)
        else:
            self._store[key] = [item]
