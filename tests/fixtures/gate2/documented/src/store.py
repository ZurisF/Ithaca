class Store:
    def __init__(self) -> None:
        self.records: list[str] = []

    def insert(self, name: str) -> int:
        self.records.append(name)
        return len(self.records)
