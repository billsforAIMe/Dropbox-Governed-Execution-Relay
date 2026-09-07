from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_PROCESS_MODULE_IMPORTS = {"subprocess", "pty", "multiprocessing", "posix"}
PROCESS_START_TARGETS = {
    "subprocess.Popen", "subprocess.run", "subprocess.call", "subprocess.check_call",
    "subprocess.check_output", "subprocess.getoutput", "subprocess.getstatusoutput",
    "os.system", "os.popen", "os.fork", "os.forkpty", "os.posix_spawn", "os.posix_spawnp", "os.startfile",
    "asyncio.create_subprocess_exec", "asyncio.create_subprocess_shell",
    "pty.spawn", "multiprocessing.Process", "multiprocessing.Pool",
    "concurrent.futures.ProcessPoolExecutor",
}
PROCESS_START_PREFIXES = ("os.spawn", "os.exec", "posix.spawn", "posix.exec")
SEMANTIC_EXECUTE_ALLOWLIST = {
    ("src/dger/relay_moh_invoke.py", "RelayMohInvokeMixin._invoke_moh", "self.gateway.invoke"),
    ("src/dger/gen4_effect.py", "Gen4EffectMixin._execute_moh", "self.peers.moh_execute"),
    ("src/dger/gen4_runtime_peers.py", "Gen4RuntimePeers._invoke", "self.invoker.invoke"),
    ("src/dger/gen4_runtime_peers.py", "Gen4RuntimePeers.moh_execute", "self._invoke"),
}


def _raw_target(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _raw_target(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _constant_string(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _import_aliases(tree: ast.AST) -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                local = item.asname or item.name.split(".", 1)[0]
                aliases.setdefault(local, set()).add(item.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                if item.name == "*":
                    continue
                aliases.setdefault(item.asname or item.name, set()).add(f"{node.module}.{item.name}")
    return aliases


def _assignment_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        out: list[str] = []
        for item in node.elts:
            out.extend(_assignment_names(item))
        return out
    return []


def _resolve_value_targets(node: ast.AST, aliases: dict[str, set[str]]) -> set[str]:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, {node.id})
    if isinstance(node, ast.Attribute):
        bases = _resolve_value_targets(node.value, aliases)
        return {f"{base}.{node.attr}" for base in bases} if bases else {node.attr}
    if isinstance(node, ast.Call):
        raw = _raw_target(node.func)
        resolved_func = _resolve_value_targets(node.func, aliases)
        if raw == "__import__" and node.args:
            module = _constant_string(node.args[0])
            return {module} if module else {"<dynamic-import>"}
        if "importlib.import_module" in resolved_func and node.args:
            module = _constant_string(node.args[0])
            return {module} if module else {"<dynamic-import>"}
        if raw == "getattr" and len(node.args) >= 2:
            bases = _resolve_value_targets(node.args[0], aliases)
            attr = _constant_string(node.args[1])
            if attr is not None:
                return {f"{base}.{attr}" for base in bases}
            if any(base == "os" or base in FORBIDDEN_PROCESS_MODULE_IMPORTS for base in bases):
                return {f"{base}.<dynamic>" for base in bases}
    raw = _raw_target(node)
    if raw is None:
        return set()
    head, dot, tail = raw.partition(".")
    mapped = aliases.get(head)
    if not mapped:
        return {raw}
    return {base + (dot + tail if dot else "") for base in mapped}


def _symbol_aliases(tree: ast.AST) -> dict[str, set[str]]:
    aliases = _import_aliases(tree)
    assignments: list[tuple[list[str], ast.AST]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names: list[str] = []
            for target in node.targets:
                names.extend(_assignment_names(target))
            if names:
                assignments.append((names, node.value))
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            names = _assignment_names(node.target)
            if names:
                assignments.append((names, node.value))
        elif isinstance(node, ast.NamedExpr):
            names = _assignment_names(node.target)
            if names:
                assignments.append((names, node.value))

    # Conservative fixed point: once a symbol is known to have referenced a process
    # callable, later rebinding never erases that fact. This intentionally favors
    # false-positive review over an execution-surface false negative.
    changed = True
    while changed:
        changed = False
        for names, value in assignments:
            resolved = _resolve_value_targets(value, aliases)
            if not resolved:
                continue
            for name in names:
                bucket = aliases.setdefault(name, set())
                before = len(bucket)
                bucket.update(resolved)
                if len(bucket) != before:
                    changed = True
    return aliases


def _expr_marker(node: ast.AST) -> str | None:
    value = _constant_string(node)
    if value is not None:
        return value
    if isinstance(node, ast.Name):
        return node.id
    return _raw_target(node)


def _is_process_target(target: str) -> bool:
    return target in PROCESS_START_TARGETS or any(target.startswith(prefix) for prefix in PROCESS_START_PREFIXES)


def _is_semantic_execute_call(call: ast.Call, raw_target: str | None) -> bool:
    if raw_target is None:
        return False
    tail = raw_target.rsplit(".", 1)[-1]
    if tail in {"moh_execute", "execute"}:
        return True
    markers = [_expr_marker(x) for x in call.args]
    markers.extend(_expr_marker(x.value) for x in call.keywords)
    if tail == "_invoke":
        return "MOH_EXECUTE_OPERATION" in markers or "execute" in markers
    if tail == "invoke":
        if len(call.args) >= 3 and _expr_marker(call.args[2]) == "READ":
            return False
        if raw_target == "self.invoker.invoke" and len(call.args) >= 3:
            return True
        if len(call.args) >= 2:
            operation = _expr_marker(call.args[1])
            if operation in {"execute", "MOH_EXECUTE_OPERATION"}:
                return True
            if isinstance(call.args[1], ast.Constant) and isinstance(call.args[1].value, str):
                return False
            return True
        return True
    return False


class _ExecutionCallVisitor(ast.NodeVisitor):
    def __init__(self, rel: str, aliases: dict[str, set[str]]) -> None:
        self.rel = rel
        self.aliases = aliases
        self.scope: list[str] = []
        self.process_calls: list[tuple[str, str, str, int]] = []
        self.semantic_calls: list[tuple[str, str, str, int]] = []
        self._seen_process: set[tuple[str, str, str, int]] = set()

    def _qualname(self) -> str:
        return ".".join(self.scope) if self.scope else "<module>"

    def _record_process(self, target: str, lineno: int) -> None:
        row = (self.rel, self._qualname(), target, lineno)
        if row not in self._seen_process:
            self._seen_process.add(row)
            self.process_calls.append(row)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_Import(self, node: ast.Import) -> None:
        for item in node.names:
            root = item.name.split(".", 1)[0]
            if root in FORBIDDEN_PROCESS_MODULE_IMPORTS:
                self._record_process(f"import:{item.name}", node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            root = node.module.split(".", 1)[0]
            if root in FORBIDDEN_PROCESS_MODULE_IMPORTS:
                self._record_process(f"import:{node.module}", node.lineno)
            for item in node.names:
                if item.name == "*" and root in {"os", *FORBIDDEN_PROCESS_MODULE_IMPORTS}:
                    self._record_process(f"import:{node.module}.*", node.lineno)
                target = f"{node.module}.{item.name}"
                if _is_process_target(target):
                    self._record_process(target, node.lineno)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        raw = _raw_target(node.func)
        resolved = _resolve_value_targets(node.func, self.aliases)
        for target in sorted(resolved):
            if _is_process_target(target):
                self._record_process(target, node.lineno)
        produced = _resolve_value_targets(node, self.aliases)
        for target in sorted(produced):
            if _is_process_target(target):
                self._record_process(target, node.lineno)
            if target == "<dynamic-import>" or target.endswith(".<dynamic>"):
                self._record_process(target, node.lineno)
            if target in FORBIDDEN_PROCESS_MODULE_IMPORTS:
                self._record_process(f"dynamic-import:{target}", node.lineno)
        if _is_semantic_execute_call(node, raw):
            self.semantic_calls.append((self.rel, self._qualname(), raw or "<dynamic>", node.lineno))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        for target in sorted(_resolve_value_targets(node, self.aliases)):
            if _is_process_target(target):
                self._record_process(target, node.lineno)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        for target in sorted(_resolve_value_targets(node, self.aliases)):
            if _is_process_target(target):
                self._record_process(target, node.lineno)
        self.generic_visit(node)


def scan_execution_call_sites(root: Path) -> tuple[list[tuple[str, str, str, int]], list[tuple[str, str, str, int]]]:
    process_calls: list[tuple[str, str, str, int]] = []
    semantic_calls: list[tuple[str, str, str, int]] = []
    src = root / "src/dger"
    if src.is_symlink() or not src.is_dir():
        raise ValueError("UNSAFE_SOURCE_ROOT:src/dger")
    python_files: list[Path] = []
    for path in sorted(src.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"UNSAFE_SOURCE_PATH:{path.relative_to(root).as_posix()}")
        if path.suffix == ".py":
            if not path.is_file():
                raise ValueError(f"UNSAFE_SOURCE_PATH:{path.relative_to(root).as_posix()}")
            python_files.append(path)
    for path in python_files:
        rel = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        visitor = _ExecutionCallVisitor(rel, _symbol_aliases(tree))
        visitor.visit(tree)
        process_calls.extend(visitor.process_calls)
        semantic_calls.extend(visitor.semantic_calls)
    triples = [(p, q, t) for p, q, t, _ in semantic_calls]
    if len(triples) != len(set(triples)):
        raise ValueError("DUPLICATE_SEMANTIC_EXECUTION_CALL_SITE")
    return process_calls, semantic_calls
