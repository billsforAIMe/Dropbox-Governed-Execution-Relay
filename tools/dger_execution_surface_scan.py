from __future__ import annotations

import ast
from pathlib import Path

PROCESS_START_TARGETS = {
    "subprocess.Popen", "subprocess.run", "subprocess.call", "subprocess.check_call",
    "subprocess.check_output", "subprocess.getoutput", "subprocess.getstatusoutput",
    "os.system", "os.popen", "os.fork", "os.forkpty", "os.posix_spawn", "os.posix_spawnp",
    "asyncio.create_subprocess_exec", "asyncio.create_subprocess_shell",
    "pty.spawn", "multiprocessing.Process",
}
PROCESS_START_PREFIXES = ("os.spawn", "os.exec")
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


def _resolve_targets(node: ast.AST, aliases: dict[str, set[str]]) -> set[str]:
    raw = _raw_target(node)
    if raw is None:
        return set()
    head, dot, tail = raw.partition(".")
    mapped = aliases.get(head)
    if not mapped:
        return {raw}
    return {base + (dot + tail if dot else "") for base in mapped}


def _expr_marker(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return node.id
    return _raw_target(node)


def _is_process_start(targets: set[str]) -> bool:
    return any(
        target in PROCESS_START_TARGETS
        or any(target.startswith(prefix) for prefix in PROCESS_START_PREFIXES)
        for target in targets
    )


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
        # Protected invoke(tool, operation, authority_class, ...) is non-executing only
        # when the authority class is statically READ. Dynamic/effectful authority remains
        # an execution-capable boundary. Legacy invoke(tool, operation, ...) similarly
        # remains execution-capable when the operation is dynamic.
        if raw_target == "self.invoker.invoke" and len(call.args) >= 3:
            authority = _expr_marker(call.args[2])
            if authority == "READ":
                return False
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

    def _qualname(self) -> str:
        return ".".join(self.scope) if self.scope else "<module>"

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

    def visit_Call(self, node: ast.Call) -> None:
        raw = _raw_target(node.func)
        resolved = _resolve_targets(node.func, self.aliases)
        if _is_process_start(resolved):
            self.process_calls.append((self.rel, self._qualname(), "|".join(sorted(resolved)), node.lineno))
        if _is_semantic_execute_call(node, raw):
            self.semantic_calls.append((self.rel, self._qualname(), raw or "<dynamic>", node.lineno))
        self.generic_visit(node)


def scan_execution_call_sites(root: Path) -> tuple[list[tuple[str, str, str, int]], list[tuple[str, str, str, int]]]:
    process_calls: list[tuple[str, str, str, int]] = []
    semantic_calls: list[tuple[str, str, str, int]] = []
    src = root / "src/dger"
    for path in sorted(src.rglob("*.py")):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"UNSAFE_SOURCE_PATH:{path.relative_to(root).as_posix()}")
        rel = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        visitor = _ExecutionCallVisitor(rel, _import_aliases(tree))
        visitor.visit(tree)
        process_calls.extend(visitor.process_calls)
        semantic_calls.extend(visitor.semantic_calls)
    return process_calls, semantic_calls
