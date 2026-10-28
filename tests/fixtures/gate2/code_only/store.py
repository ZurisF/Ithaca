class Store:
    def __init__(self) -> None:
        self.values: list[int] = []

    def save(self, value: int) -> int:
        self.values.append(value)
        return len(self.values)
