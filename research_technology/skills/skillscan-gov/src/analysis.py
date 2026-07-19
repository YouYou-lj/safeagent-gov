"""Non-executing Python AST and JavaScript/TypeScript syntax-tree analyzers."""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass
from typing import Any

SENSITIVE_TERMS = {".env", ".ssh", "id_rsa", "token", "secret", "password", "cookie", "credential", "api_key"}

PYTHON_CALL_CATEGORIES = {
    "command_execution": {
        "os.system",
        "subprocess.run",
        "subprocess.call",
        "subprocess.Popen",
        "subprocess.check_call",
        "subprocess.check_output",
    },
    "network_exfiltration": {
        "requests.get",
        "requests.post",
        "requests.put",
        "requests.patch",
        "urllib.request.urlopen",
        "http.client.HTTPConnection",
        "http.client.HTTPSConnection",
        "socket.connect",
        "socket.create_connection",
        "socket.socket.connect",
    },
    "dynamic_loading": {"eval", "exec", "compile", "__import__", "importlib.import_module", "runpy.run_path"},
    "obfuscation": {"base64.b64decode", "codecs.decode", "marshal.loads", "zlib.decompress"},
    "persistence": {"crontab.CronTab", "winreg.SetValue", "winreg.SetValueEx", "atexit.register"},
}

JS_CALL_CATEGORIES = {
    "command_execution": {
        "child_process.exec",
        "child_process.execSync",
        "child_process.spawn",
        "child_process.spawnSync",
        "exec",
        "execSync",
        "spawn",
        "spawnSync",
    },
    "network_exfiltration": {
        "fetch",
        "axios.get",
        "axios.post",
        "http.request",
        "https.request",
        "net.connect",
        "WebSocket",
    },
    "dynamic_loading": {"eval", "Function", "import"},
    "obfuscation": {"atob", "Buffer.from", "String.fromCharCode"},
    "persistence": {"registry.set", "cron.schedule"},
}


def _contains_sensitive(value: str) -> bool:
    lowered = value.casefold()
    return any(term in lowered for term in SENSITIVE_TERMS)


def _qualified_python(node: ast.AST, aliases: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        parent = _qualified_python(node.value, aliases)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _matches_api(name: str, candidates: set[str]) -> bool:
    return any(name == candidate or name.startswith(candidate + ".") for candidate in candidates)


def _classify_call(name: str, mapping: dict[str, set[str]]) -> str | None:
    for category, candidates in mapping.items():
        if _matches_api(name, candidates):
            return category
    return None


def _python_token_guard(content: str, max_tokens: int, max_depth: int) -> None:
    depth = count = 0
    try:
        stream = tokenize.generate_tokens(io.StringIO(content).readline)
        for token in stream:
            count += 1
            if count > max_tokens:
                raise ValueError("Python token 数超过安全上限")
            if token.string in {"(", "[", "{"}:
                depth += 1
                if depth > max_depth:
                    raise ValueError("Python 语法嵌套超过安全上限")
            elif token.string in {")",
                "]",
                "}",
            }:
                depth = max(0, depth - 1)
    except (IndentationError, tokenize.TokenError) as exc:
        raise SyntaxError(str(exc)) from exc


class _PythonFacts(ast.NodeVisitor):
    def __init__(self, path: str, aliases: dict[str, str], sensitive_functions: set[str]) -> None:
        self.path = path
        self.aliases = aliases
        self.sensitive_functions = sensitive_functions
        self.function_stack: list[str] = []
        self.function_ids: list[str] = []
        self.tainted: list[set[str]] = [set()]
        self.evidence: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self.assignments: list[dict[str, Any]] = []
        self.sinks: list[dict[str, Any]] = []
        self.graph_nodes: list[dict[str, Any]] = []
        self.graph_edges: list[dict[str, Any]] = []

    @property
    def scope(self) -> str:
        return self.function_stack[-1] if self.function_stack else "<module>"

    def _node_id(self, kind: str, line: int, name: str) -> str:
        return f"{self.path}:{kind}:{line}:{name}"

    def _add_evidence(self, category: str, node: ast.AST, api: str, detail: str, confidence: float = 0.95) -> None:
        self.evidence.append(
            {
                "category": category,
                "file": self.path,
                "line": int(getattr(node, "lineno", 1)),
                "column": int(getattr(node, "col_offset", 0)) + 1,
                "symbol": self.scope,
                "api": api,
                "detail": detail,
                "confidence": confidence,
                "parser": "python_ast",
            }
        )

    def _is_sensitive_source(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Call):
            name = _qualified_python(node.func, self.aliases)
            if name in {"open", "pathlib.Path.read_text", "pathlib.Path.read_bytes"}:
                return any(isinstance(arg, ast.Constant) and isinstance(arg.value, str) and _contains_sensitive(arg.value) for arg in node.args)
            if name in {"os.getenv", "os.environ.get"}:
                return any(isinstance(arg, ast.Constant) and isinstance(arg.value, str) and _contains_sensitive(arg.value) for arg in node.args)
            simple = name.rsplit(".", 1)[-1]
            if simple in self.sensitive_functions:
                return True
            return any(self._is_sensitive_source(child) for child in ast.iter_child_nodes(node))
        if isinstance(node, ast.Subscript):
            name = _qualified_python(node.value, self.aliases)
            value = node.slice.value if isinstance(node.slice, ast.Constant) else None
            return name == "os.environ" and isinstance(value, str) and _contains_sensitive(value)
        if isinstance(node, ast.Name):
            return node.id in self.tainted[-1]
        return any(self._is_sensitive_source(child) for child in ast.iter_child_nodes(node))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_stack.append(node.name)
        self.tainted.append(set())
        function_id = self._node_id("function", node.lineno, node.name)
        self.graph_nodes.append({"id": function_id, "type": "function", "file": self.path, "name": node.name, "line": node.lineno})
        self.function_ids.append(function_id)
        self.generic_visit(node)
        self.function_ids.pop()
        self.tainted.pop()
        self.function_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node: ast.Assign) -> None:
        targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
        calls = [
            _qualified_python(child.func, self.aliases)
            for child in ast.walk(node.value)
            if isinstance(child, ast.Call)
        ]
        sensitive = self._is_sensitive_source(node.value)
        if sensitive:
            self.tainted[-1].update(targets)
        for target in targets:
            self.assignments.append(
                {
                    "file": self.path,
                    "line": node.lineno,
                    "scope": self.scope,
                    "target": target,
                    "source_calls": calls,
                    "sensitive": sensitive,
                }
            )
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None and isinstance(node.target, ast.Name) and self._is_sensitive_source(node.value):
            self.tainted[-1].add(node.target.id)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _qualified_python(node.func, self.aliases)
        line = int(getattr(node, "lineno", 1))
        call_id = self._node_id("call", line, name)
        self.calls.append({"file": self.path, "line": line, "scope": self.scope, "callee": name, "call_id": call_id})
        self.graph_nodes.append({"id": call_id, "type": "call", "file": self.path, "api": name, "line": line})
        self.graph_edges.append(
            {
                "from": self.function_ids[-1] if self.function_ids else f"{self.path}:module",
                "to": call_id,
                "type": "calls",
            }
        )
        category = _classify_call(name, PYTHON_CALL_CATEGORIES)
        if category:
            self._add_evidence(category, node, name, f"AST 调用 {name}")
        sensitive_source = self._is_sensitive_source(node)
        if sensitive_source and name in {"open", "os.getenv", "os.environ.get"}:
            self._add_evidence("sensitive_file_access", node, name, "读取敏感路径或凭证变量")
        is_sink = category in {"command_execution", "network_exfiltration", "dynamic_loading"}
        tainted_args = any(self._is_sensitive_source(arg) for arg in [*node.args, *[kw.value for kw in node.keywords]])
        if is_sink:
            self.sinks.append(
                {
                    "file": self.path,
                    "line": line,
                    "scope": self.scope,
                    "api": name,
                    "argument_names": sorted(
                        {
                            child.id
                            for argument in [*node.args, *[keyword.value for keyword in node.keywords]]
                            for child in ast.walk(argument)
                            if isinstance(child, ast.Name)
                        }
                    ),
                    "tainted": tainted_args,
                }
            )
        if is_sink and tainted_args:
            self._add_evidence("sensitive_data_flow", node, name, "敏感来源数据流向高风险调用", 0.99)
            source_id = self._node_id("taint", line, "sensitive")
            self.graph_nodes.append({"id": source_id, "type": "sensitive_data", "file": self.path, "line": line})
            self.graph_edges.append({"from": source_id, "to": call_id, "type": "flows_to"})
        self.generic_visit(node)


def _python_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".")[0]] = item.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for item in node.names:
                aliases[item.asname or item.name] = f"{module}.{item.name}".strip(".")
    return aliases


def _function_sensitive_returns(tree: ast.AST, aliases: dict[str, str]) -> set[str]:
    functions = {node.name: node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    sensitive: set[str] = set()
    for _ in range(len(functions) + 1):
        changed = False
        for name, function in functions.items():
            if name in sensitive:
                continue
            for node in ast.walk(function):
                if not isinstance(node, ast.Return) or node.value is None:
                    continue
                calls = [child for child in ast.walk(node.value) if isinstance(child, ast.Call)]
                if any(
                    (_qualified_python(call.func, aliases) in {"open", "os.getenv", "os.environ.get"}
                     and any(isinstance(arg, ast.Constant) and isinstance(arg.value, str) and _contains_sensitive(arg.value) for arg in call.args))
                    or _qualified_python(call.func, aliases).rsplit(".", 1)[-1] in sensitive
                    for call in calls
                ):
                    sensitive.add(name)
                    changed = True
                    break
        if not changed:
            break
    return sensitive


def analyze_python(content: str, relative_path: str, *, max_tokens: int, max_depth: int) -> dict[str, Any]:
    _python_token_guard(content, max_tokens, max_depth)
    tree = ast.parse(content, filename=relative_path, type_comments=True)
    aliases = _python_aliases(tree)
    sensitive_functions = _function_sensitive_returns(tree, aliases)
    visitor = _PythonFacts(relative_path, aliases, sensitive_functions)
    visitor.visit(tree)
    definitions = [
        {
            "file": relative_path,
            "name": node.name,
            "line": node.lineno,
            "sensitive_return": node.name in sensitive_functions,
            "node_id": f"{relative_path}:function:{node.lineno}:{node.name}",
        }
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    return {
        "language": "python",
        "evidence": visitor.evidence,
        "definitions": definitions,
        "imports": aliases,
        "calls": visitor.calls,
        "assignments": visitor.assignments,
        "sinks": visitor.sinks,
        "graph_nodes": visitor.graph_nodes,
        "graph_edges": visitor.graph_edges,
    }


@dataclass(frozen=True)
class JsToken:
    kind: str
    value: str
    line: int


def _lex_javascript(content: str, *, max_tokens: int, max_depth: int) -> list[JsToken]:
    tokens: list[JsToken] = []
    index = 0
    line = 1
    depth = 0
    length = len(content)
    while index < length:
        char = content[index]
        if char.isspace():
            line += int(char == "\n")
            index += 1
            continue
        if content.startswith("//", index):
            end = content.find("\n", index)
            index = length if end < 0 else end
            continue
        if content.startswith("/*", index):
            end = content.find("*/", index + 2)
            if end < 0:
                raise SyntaxError("未闭合的 JavaScript 块注释")
            line += content[index:end + 2].count("\n")
            index = end + 2
            continue
        if char in {'"', "'", "`"}:
            quote = char
            start_line = line
            index += 1
            value = []
            while index < length:
                current = content[index]
                if current == "\\":
                    if index + 1 < length:
                        value.extend([current, content[index + 1]])
                        line += int(content[index + 1] == "\n")
                        index += 2
                        continue
                if current == quote:
                    index += 1
                    break
                value.append(current)
                line += int(current == "\n")
                index += 1
            else:
                raise SyntaxError("未闭合的 JavaScript 字符串")
            tokens.append(JsToken("string", "".join(value), start_line))
        elif char.isalpha() or char in {"_", "$"}:
            start = index
            while index < length and (content[index].isalnum() or content[index] in {"_", "$"}):
                index += 1
            tokens.append(JsToken("identifier", content[start:index], line))
        elif char.isdigit():
            start = index
            while index < length and (content[index].isdigit() or content[index] in {".", "_"}):
                index += 1
            tokens.append(JsToken("number", content[start:index], line))
        else:
            if char in "([{":
                depth += 1
                if depth > max_depth:
                    raise ValueError("JavaScript/TypeScript 语法嵌套超过安全上限")
            elif char in ")]}":
                depth = max(0, depth - 1)
            two = content[index:index + 2]
            if two in {"=>", "?.", "==", "!=", "&&", "||", "??"}:
                tokens.append(JsToken("punct", two, line))
                index += 2
            else:
                tokens.append(JsToken("punct", char, line))
                index += 1
        if len(tokens) > max_tokens:
            raise ValueError("JavaScript/TypeScript token 数超过安全上限")
    return tokens


def _js_member_before(tokens: list[JsToken], paren_index: int) -> str:
    parts: list[str] = []
    index = paren_index - 1
    while index >= 0:
        token = tokens[index]
        if token.kind == "identifier":
            parts.append(token.value)
            index -= 1
            if index >= 0 and tokens[index].value in {".", "?."}:
                index -= 1
                continue
            break
        break
    return ".".join(reversed(parts))


def _js_argument_tokens(tokens: list[JsToken], open_index: int) -> list[JsToken]:
    depth = 0
    output: list[JsToken] = []
    for token in tokens[open_index + 1:]:
        if token.value == "(":
            depth += 1
        elif token.value == ")":
            if depth == 0:
                break
            depth -= 1
        output.append(token)
    return output


def analyze_javascript(content: str, relative_path: str, *, max_tokens: int, max_depth: int) -> dict[str, Any]:
    tokens = _lex_javascript(content, max_tokens=max_tokens, max_depth=max_depth)
    aliases: dict[str, str] = {}
    definitions: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []
    sinks: list[dict[str, Any]] = []
    graph_nodes: list[dict[str, Any]] = []
    graph_edges: list[dict[str, Any]] = []
    tainted: set[str] = set()

    # Resolve ES modules and CommonJS aliases before classifying calls.
    for index, token in enumerate(tokens):
        if token.value == "import":
            from_index = next(
                (position for position in range(index + 1, min(len(tokens), index + 40)) if tokens[position].value == "from"),
                None,
            )
            if from_index is not None and from_index + 1 < len(tokens) and tokens[from_index + 1].kind == "string":
                module = tokens[from_index + 1].value
                segment = tokens[index + 1:from_index]
                if segment and segment[0].kind == "identifier" and not any(item.value == "{" for item in segment):
                    aliases[segment[0].value] = module
                if any(item.value == "{" for item in segment):
                    groups: list[list[JsToken]] = [[]]
                    for item in segment:
                        if item.value == ",":
                            groups.append([])
                        elif item.value not in {"{", "}"}:
                            groups[-1].append(item)
                    for group in groups:
                        names = [item.value for item in group if item.kind == "identifier" and item.value != "as"]
                        if not names:
                            continue
                        imported = names[0]
                        local = names[-1]
                        aliases[local] = f"{module}.{imported}"
        if token.value == "require" and index + 2 < len(tokens) and tokens[index + 1].value == "(" and tokens[index + 2].kind == "string":
            module = tokens[index + 2].value
            if index >= 2 and tokens[index - 1].value == "=":
                if tokens[index - 2].kind == "identifier":
                    aliases[tokens[index - 2].value] = module
                elif tokens[index - 2].value == "}":
                    start = index - 3
                    while start >= 0 and tokens[start].value != "{":
                        start -= 1
                    for item in tokens[start + 1:index - 2]:
                        if item.kind == "identifier":
                            aliases[item.value] = f"{module}.{item.value}"

    for index, token in enumerate(tokens):
        if token.value == "function" and index + 1 < len(tokens) and tokens[index + 1].kind == "identifier":
            name = tokens[index + 1].value
            open_brace = next(
                (position for position in range(index + 2, min(len(tokens), index + 80)) if tokens[position].value == "{"),
                None,
            )
            sensitive_return = False
            if open_brace is not None:
                depth = 0
                body: list[JsToken] = []
                for item in tokens[open_brace + 1:]:
                    if item.value == "{":
                        depth += 1
                    elif item.value == "}":
                        if depth == 0:
                            break
                        depth -= 1
                    body.append(item)
                sensitive_return = any(item.value == "return" for item in body) and (
                    any(item.kind == "string" and _contains_sensitive(item.value) for item in body)
                    or (any(item.value == "env" for item in body) and any(_contains_sensitive(item.value) for item in body))
                )
            definitions.append(
                {
                    "file": relative_path,
                    "name": name,
                    "line": token.line,
                    "sensitive_return": sensitive_return,
                    "node_id": f"{relative_path}:function:{token.line}:{name}",
                }
            )
        if (
            token.kind == "identifier"
            and index + 3 < len(tokens)
            and tokens[index + 1].value == "="
            and tokens[index + 2].value in {"(", "async"}
            and any(item.value == "=>" for item in tokens[index + 2:index + 12])
        ):
            definitions.append(
                {
                    "file": relative_path,
                    "name": token.value,
                    "line": token.line,
                    "sensitive_return": False,
                    "node_id": f"{relative_path}:function:{token.line}:{token.value}",
                }
            )
        if token.kind == "identifier" and index + 1 < len(tokens) and tokens[index + 1].value == "=":
            rhs = tokens[index + 2:]
            end = next((offset for offset, item in enumerate(rhs) if item.value == ";"), len(rhs))
            rhs = rhs[:end]
            source_calls = []
            sensitive = any(item.kind == "string" and _contains_sensitive(item.value) for item in rhs)
            sensitive |= any(item.value == "env" for item in rhs) and any(_contains_sensitive(item.value) for item in rhs)
            for pos, item in enumerate(rhs):
                if item.value == "(" and pos > 0:
                    source_name = _js_member_before(rhs, pos)
                    root, *rest = source_name.split(".")
                    source_calls.append(".".join([aliases.get(root, root), *rest]))
            if sensitive:
                tainted.add(token.value)
            assignments.append(
                {
                    "file": relative_path,
                    "line": token.line,
                    "scope": "<module>",
                    "target": token.value,
                    "source_calls": source_calls,
                    "sensitive": sensitive,
                }
            )
        if token.value != "(":
            continue
        name = _js_member_before(tokens, index)
        if not name:
            continue
        root, *rest = name.split(".")
        canonical = ".".join([aliases.get(root, root), *rest])
        args = _js_argument_tokens(tokens, index)
        category = _classify_call(canonical, JS_CALL_CATEGORIES)
        call_id = f"{relative_path}:call:{token.line}:{canonical}"
        calls.append(
            {"file": relative_path, "line": token.line, "scope": "<module>", "callee": canonical, "call_id": call_id}
        )
        graph_nodes.append({"id": call_id, "type": "call", "file": relative_path, "api": canonical, "line": token.line})
        graph_edges.append({"from": f"{relative_path}:module", "to": call_id, "type": "calls"})
        if canonical == "require" and (not args or args[0].kind != "string"):
            category = "dynamic_loading"
        if category:
            evidence.append(
                {
                    "category": category,
                    "file": relative_path,
                    "line": token.line,
                    "column": 1,
                    "symbol": "<module>",
                    "api": canonical,
                    "detail": f"JavaScript/TypeScript 结构化调用 {canonical}",
                    "confidence": 0.9,
                    "parser": "javascript_syntax_tree",
                }
            )
        sensitive = any(item.kind == "string" and _contains_sensitive(item.value) for item in args)
        sensitive |= any(item.value in tainted for item in args if item.kind == "identifier")
        sensitive |= canonical in {"fs.readFile", "fs.readFileSync"} and any(_contains_sensitive(item.value) for item in args if item.kind == "string")
        if canonical in {"fs.readFile", "fs.readFileSync"} and sensitive:
            evidence.append(
                {
                    "category": "sensitive_file_access",
                    "file": relative_path,
                    "line": token.line,
                    "column": 1,
                    "symbol": "<module>",
                    "api": canonical,
                    "detail": "读取敏感文件或凭证",
                    "confidence": 0.95,
                    "parser": "javascript_syntax_tree",
                }
            )
        if category in {"command_execution", "network_exfiltration", "dynamic_loading"}:
            sinks.append(
                {
                    "file": relative_path,
                    "line": token.line,
                    "scope": "<module>",
                    "api": canonical,
                    "argument_names": sorted({item.value for item in args if item.kind == "identifier"}),
                    "tainted": sensitive,
                }
            )
            if sensitive:
                evidence.append(
                    {
                        "category": "sensitive_data_flow",
                        "file": relative_path,
                        "line": token.line,
                        "column": 1,
                        "symbol": "<module>",
                        "api": canonical,
                        "detail": "敏感来源数据流向高风险调用",
                        "confidence": 0.95,
                        "parser": "javascript_syntax_tree",
                    }
                )
    return {
        "language": "javascript_typescript",
        "evidence": evidence,
        "definitions": definitions,
        "imports": aliases,
        "calls": calls,
        "assignments": assignments,
        "sinks": sinks,
        "graph_nodes": graph_nodes,
        "graph_edges": graph_edges,
    }


def analyze_text_fallback(content: str, relative_path: str) -> dict[str, Any]:
    """Line-aware shell/config fallback; it is not used for Python or JS/TS."""
    evidence: list[dict[str, Any]] = []
    patterns = {
        "command_execution": re.compile(r"\b(?:bash|sh|powershell|cmd|eval)\b", re.I),
        "network_exfiltration": re.compile(r"\b(?:curl|wget|nc|netcat)\b", re.I),
        "persistence": re.compile(r"\b(?:crontab|launchctl|systemctl\s+enable|schtasks)\b", re.I),
    }
    for line_number, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//")):
            continue
        for category, pattern in patterns.items():
            match = pattern.search(stripped)
            if match:
                evidence.append(
                    {
                        "category": category,
                        "file": relative_path,
                        "line": line_number,
                        "column": match.start() + 1,
                        "symbol": "<text>",
                        "api": match.group(0),
                        "detail": "行级脚本/配置行为",
                        "confidence": 0.65,
                        "parser": "text_fallback",
                    }
                )
    return {
        "language": "text",
        "evidence": evidence,
        "definitions": [],
        "imports": {},
        "calls": [],
        "assignments": [],
        "sinks": [],
        "graph_nodes": [],
        "graph_edges": [],
    }
