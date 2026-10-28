"""Bounded, deterministic navigation map; never a second project snapshot."""

import ast
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from local_project.inventory.walk import InventoryItem
from local_project.tools.read_only import read_file_text

SYMBOL = re.compile(
    r"(?m)^\s*(?:export\s+)?(?:public\s+)?(?:async\s+)?"
    r"(class|interface|def|function|func|fn|type)\s+([A-Za-z_][A-Za-z_0-9]*)"
)
FRAMEWORK_SIGNALS = {
    "FastAPI": re.compile(r"\bfastapi\b", re.IGNORECASE),
    "Next.js": re.compile(r"\bnext(?:\.js)?\b", re.IGNORECASE),
    "React": re.compile(r"\breact\b", re.IGNORECASE),
    "Django": re.compile(r"\bdjango\b", re.IGNORECASE),
    "Flask": re.compile(r"\bflask\b", re.IGNORECASE),
    "Spring": re.compile(r"\bspring[-.]boot\b", re.IGNORECASE),
}
LANGUAGES = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
}


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str
    line: int
    signature: str


@dataclass(frozen=True)
class RepositoryMap:
    text: str
    included_paths: tuple[str, ...]
    omitted_files: int
    partial: bool


def file_symbols(path: str, content: str) -> list[Symbol]:
    """Use Python AST where possible, with a conservative text fallback."""
    if Path(path).suffix.lower() == ".py":
        try:
            tree = ast.parse(content)
            symbols: list[Symbol] = []
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    arguments = ", ".join(arg.arg for arg in node.args.args)
                    symbols.append(
                        Symbol(node.name, "function", node.lineno, f"{node.name}({arguments})")
                    )
                elif isinstance(node, ast.ClassDef):
                    symbols.append(Symbol(node.name, "class", node.lineno, node.name))
                    for child in node.body:
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            arguments = ", ".join(arg.arg for arg in child.args.args)
                            symbols.append(
                                Symbol(
                                    f"{node.name}.{child.name}",
                                    "method",
                                    child.lineno,
                                    f"{node.name}.{child.name}({arguments})",
                                )
                            )
            return symbols[:40]
        except SyntaxError:
            pass
    return [
        Symbol(
            match.group(2),
            match.group(1),
            content.count("\n", 0, match.start()) + 1,
            match.group(2),
        )
        for match in list(SYMBOL.finditer(content))[:40]
    ]


def _priority(path: str) -> tuple[int, str]:
    name = Path(path).name.casefold()
    score = 0
    if name.startswith("readme"):
        score += 100
    if name in {"pyproject.toml", "package.json", "go.mod", "cargo.toml", "pom.xml"}:
        score += 85
    if name in {"main.py", "app.py", "index.ts", "index.js", "server.ts", "server.js"}:
        score += 75
    if name in {"dockerfile", "compose.yaml", "docker-compose.yml"}:
        score += 55
    if "/src/" in f"/{path}" or path.startswith("src/"):
        score += 30
    if "test" in path.casefold():
        score += 15
    return (-score, path)


def build_repository_map(
    root: Path,
    items: list[InventoryItem],
    *,
    max_files: int = 120,
    max_chars: int = 20_000,
    inventory_partial: bool = False,
) -> RepositoryMap:
    eligible = sorted(
        (item for item in items if item.kind == "file" and item.skip_reason is None),
        key=lambda item: _priority(item.relative_path),
    )
    chosen = eligible[:max_files]
    omitted = len(eligible) - len(chosen)
    directories = sorted({str(Path(item.relative_path).parent) for item in eligible})
    languages = Counter(
        LANGUAGES[Path(item.relative_path).suffix.lower()]
        for item in eligible
        if Path(item.relative_path).suffix.lower() in LANGUAGES
    )
    lines = [
        "# Repository Map (navigation data; verify claims by reading files)",
        "Directories: " + ", ".join(directories[:50])[:1_000],
        "Languages: " + ", ".join(f"{name} {count}" for name, count in languages.most_common()),
    ]
    included = []
    frameworks = set()
    body_budget = max(200, max_chars - 250)
    for index, item in enumerate(chosen):
        try:
            content = read_file_text(root, item.relative_path)
        except Exception:  # noqa: BLE001 - changed files are omitted, never trusted by map
            omitted += 1
            continue
        if Path(item.relative_path).name.casefold() in {
            "pyproject.toml",
            "package.json",
            "go.mod",
            "cargo.toml",
            "pom.xml",
        }:
            frameworks.update(
                name for name, pattern in FRAMEWORK_SIGNALS.items() if pattern.search(content)
            )
        symbols = file_symbols(item.relative_path, content)
        entry = f"- {item.relative_path}"
        if symbols:
            entry += " | " + "; ".join(
                f"{symbol.kind} {symbol.signature}:L{symbol.line}" for symbol in symbols[:12]
            )
        if len("\n".join([*lines, entry])) > body_budget:
            omitted += len(chosen) - index
            break
        lines.append(entry)
        included.append(item.relative_path)
    lines.insert(3, "Framework signals: " + (", ".join(sorted(frameworks)) or "not confirmed"))
    partial = inventory_partial or omitted > 0
    lines.append(
        f"Coverage: {len(included)} mapped files; {omitted} omitted; partial={str(partial).lower()}"
    )
    return RepositoryMap("\n".join(lines)[:max_chars], tuple(included), omitted, partial)
