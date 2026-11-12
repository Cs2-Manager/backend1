"""Conservative local estimate from the 28/10/2026 guide, NOT the evaluator.

Run from back/: python scripts/estimate_flask_quality.py docs/quality-initial.json
All repository Python files (including this tool, tests and migrations) count.
The algorithm is frozen before application refactoring; source hashes are saved.
"""

import ast
import builtins
from collections import Counter, defaultdict
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tokenize

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", "venv", ".venv", "__pycache__", ".pytest_cache", "coverage", "node_modules", "dist", "build"}
DECISIONS = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
             ast.With, ast.AsyncWith, ast.Assert, ast.IfExp)
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def decision_points(node):
    if isinstance(node, ast.BoolOp):
        return len(node.values) - 1
    if isinstance(node, ast.comprehension):
        return len(node.ifs)
    return int(isinstance(node, DECISIONS))


def test_path(path):
    return "tests" in path.parts or path.name.startswith("test_")


def included(path):
    return not EXCLUDED.intersection(path.parts) and (ROOT / path).stat().st_size <= 1_000_000


def docstring_ranges(tree):
    ranges = []
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            ranges.append((first.lineno, first.end_lineno))
    return ranges


def normalized(text, tree):
    omitted = set()
    for start, end in docstring_ranges(tree):
        omitted.update(range(start, end + 1))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            omitted.update(range(node.lineno, node.end_lineno + 1))
    comments = {tok.start[0]: tok.start[1] for tok in tokenize.generate_tokens(io.StringIO(text).readline) if tok.type == tokenize.COMMENT}
    result = []
    for number, line in enumerate(text.splitlines(), 1):
        value = re.sub(r"\s+", " ", line[:comments.get(number)].strip())
        if number in omitted or not value:
            continue
        if re.fullmatch(r"[\W_]+", value) or value in {"return", "break", "continue", "else:", "try:", "finally:", "pass"}:
            continue
        result.append((number, value))
    return result


def function_record(node, path, lines, methods):
    branches = Counter()
    for child in ast.walk(node):
        points = decision_points(child)
        if points:
            branches[type(child).__name__] += points
    arguments = node.args
    parameters = len(arguments.posonlyargs + arguments.args + arguments.kwonlyargs)
    parameters += int(arguments.vararg is not None) + int(arguments.kwarg is not None)
    if node in methods and arguments.args and arguments.args[0].arg in {"self", "cls"}:
        parameters -= 1
    return {"file": path.as_posix(), "name": node.name, "line": node.lineno,
            "end_line": node.end_lineno, "test": test_path(path),
            "complexity": 1 + sum(branches.values()), "branches": dict(branches),
            "nonempty_lines": sum(bool(s.strip()) for s in lines[node.lineno - 1:node.end_lineno]),
            "parameters": parameters, "method": node in methods}


def class_record(node, path, declared):
    names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name) and child.id[0].isupper()}
    external = names - declared - set(dir(builtins))
    methods = [child for child in node.body if isinstance(child, FUNCTIONS) and child.name != "__init__"]
    fields = [{child.attr for child in ast.walk(method) if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name) and child.value.id == "self"} for method in methods]
    pairs = [(a, b) for i, a in enumerate(fields) for b in fields[i + 1:]]
    shared = sum(bool(a & b) for a, b in pairs)
    all_fields = set().union(*fields)
    low = len(methods) >= 4 and len(all_fields) >= 3 and shared < len(pairs) / 2
    return {"file": path.as_posix(), "name": node.name, "line": node.lineno,
            "cbo": len(external), "external_identifiers": sorted(external),
            "low_cohesion": low, "method_pairs": len(pairs), "shared_pairs": shared}


def signal_records(path, text):
    result = []
    for number, line in enumerate(text.splitlines(), 1):
        if not test_path(path):
            if re.search(r"\bprint\s*\(|pprint\s*\(|pdb\.set_trace", line):
                result.append({"signal": "DBG", "file": path.as_posix(), "line": number})
            secret = re.search(r"(?:password|passwd|pwd|secret|api[_-]?key|token)\s*['\"]?\s*[:=]\s*['\"][^'\"]{6,}", line, re.I)
            allowed = re.search(r"os\.environ|getenv|example|placeholder|changeme|your_|xxxx|todo|\$\{|<.*>", line, re.I)
            if secret and not allowed:
                result.append({"signal": "SEC", "file": path.as_posix(), "line": number})
        if re.search(r"\b(?:select|insert|update|delete|where|from)\b.*(?:\+\s*['\"]|['\"]\s*\+|f['\"].*\{|\$\{)", line, re.I):
            result.append({"signal": "SQL", "file": path.as_posix(), "line": number})
    return result


def source_records():
    return [(p.relative_to(ROOT), p.read_bytes()) for p in sorted(ROOT.rglob("*.py")) if included(p.relative_to(ROOT))]


def inspect_sources():
    sources = source_records()
    parsed = [(p, data, ast.parse(data.decode("utf-8-sig"))) for p, data in sources]
    declared = {node.name for _, _, tree in parsed for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    result = {"files": [], "functions": [], "classes": [], "signals": []}
    windows = defaultdict(list)
    for path, data, tree in parsed:
        inspect_file(result, windows, path, data, tree, declared)
    return result, windows


def inspect_file(result, windows, path, data, tree, declared):
    text = data.decode("utf-8-sig")
    lines = text.splitlines()
    norm = normalized(text, tree)
    result["files"].append({"file": path.as_posix(), "sha256": hashlib.sha256(data).hexdigest(), "nonempty_lines": sum(bool(s.strip()) for s in lines), "normalized_lines": len(norm)})
    methods = {m for cls in ast.walk(tree) if isinstance(cls, ast.ClassDef) for m in cls.body if isinstance(m, FUNCTIONS)}
    for node in ast.walk(tree):
        if isinstance(node, FUNCTIONS):
            result["functions"].append(function_record(node, path, lines, methods))
        if isinstance(node, ast.ClassDef):
            result["classes"].append(class_record(node, path, declared))
    result["signals"].extend(signal_records(path, text))
    for i in range(len(norm) - 4):
        window = norm[i:i + 5]
        windows[tuple(value for _, value in window)].append((path.as_posix(), [n for n, _ in window]))


def summarize(result, windows):
    repeated = [occurrences for occurrences in windows.values() if len(occurrences) >= 2]
    affected = {(path, n) for occurrences in repeated for path, numbers in occurrences for n in numbers}
    total = sum(f["normalized_lines"] for f in result["files"])
    duplication = 100 * len(affected) / total
    functions = result["functions"]
    counts = Counter(s["signal"] for s in result["signals"])
    complex_functions = [f for f in functions if f["complexity"] >= 6]
    long_methods = sum(f["method"] and f["nonempty_lines"] >= 30 for f in functions)
    long_functions = sum(not f["method"] and f["nonempty_lines"] >= 30 for f in functions)
    params = sum(f["parameters"] > 4 for f in functions)
    coupling = sum(c["cbo"] >= 8 for c in result["classes"])
    cohesion = sum(c["low_cohesion"] for c in result["classes"])
    weight = 20 * counts["SEC"] + 15 * counts["SQL"] + 2 * counts["DBG"] + 5 * (len(complex_functions) + long_methods) + 4 * (long_functions + params) + 8 * (coupling + cohesion) + 1.5 * duplication
    result["summary"] = {"files": len(result["files"]), "loc": sum(f["nonempty_lines"] for f in result["files"]), "complexity": len(complex_functions), "complexity_non_test": sum(not f["test"] for f in complex_functions), "complexity_tests": sum(f["test"] for f in complex_functions), "long_methods": long_methods, "long_functions": long_functions, "long_params": params, "size": long_methods + long_functions + params, "coupling": coupling, "cohesion": cohesion, "signals": dict(counts), "normalized_lines": total, "duplicate_unique_lines": len(affected), "duplication_pct": duplication, "weight_raw": weight, "index_raw": round(4000 / (weight + 40))}
    result["duplicated_lines"] = sorted(f"{p}:{n}" for p, n in affected)
    result["limitations"] = ["Not the official evaluator; AST walks include nested functions and assertions, including tests", "Comprehension filters counted; generator iteration not added unless an explicit For node", "CBO approximate capitalized AST Name identifiers; may differ from official regex", "Raw signals need review; tool source itself can match regex", "All Python files including this estimator count; no production/test/migration exclusions"]


if __name__ == "__main__":
    result, windows = inspect_sources()
    summarize(result, windows)
    Path(sys.argv[1]).parent.mkdir(parents=True, exist_ok=True)
    Path(sys.argv[1]).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps(result["summary"], indent=2) + "\n")
