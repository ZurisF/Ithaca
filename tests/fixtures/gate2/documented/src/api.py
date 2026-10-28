from .store import Store


def handle(payload: dict, store: Store) -> int:
    name = payload.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("name required")
    return store.insert(name)
