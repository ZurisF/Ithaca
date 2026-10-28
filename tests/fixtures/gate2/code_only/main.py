from store import Store


def receive(payload: dict, store: Store) -> int:
    value = payload["value"]
    if not isinstance(value, int):
        raise TypeError("value must be integer")
    return store.save(value)
