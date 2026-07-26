from __future__ import annotations

import re
import shlex
from dataclasses import dataclass


@dataclass(frozen=True)
class ShellDependencySpec:
    dependency_type: str
    target_path: str | None
    call_expression: str
    arguments: tuple[str, ...]
    condition_expression: str | None
    source_line_start: int
    source_line_end: int
    confidence_level: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ShellParseResult:
    dependencies: tuple[ShellDependencySpec, ...]
    variables: dict[str, str]
    warnings: tuple[str, ...]


_CLIENTS = {"sqlplus", "gsql", "psql", "mysql", "beeline", "spark-sql"}
_ASSIGNMENT = re.compile(r"^(?:export\s+)?([A-Za-z_][\w]*)=(?:['\"])?([^'\"]*)(?:['\"])?$")


def parse_shell_dependencies(content: str) -> ShellParseResult:
    """Parse common batch-script calls as text; no process is ever started."""

    variables: dict[str, str] = {}
    dependencies: list[ShellDependencySpec] = []
    warnings: list[str] = []
    condition: str | None = None
    for line_number, original in enumerate(content.splitlines(), start=1):
        line = original.strip()
        if not line or line.startswith("#"):
            continue
        assignment = _ASSIGNMENT.match(line)
        if assignment:
            variables[assignment.group(1)] = assignment.group(2)
            continue
        if re.match(r"^(if|elif|while|for)\b", line):
            condition = line
        if line in {"fi", "done"}:
            condition = None
            continue
        try:
            tokens = shlex.split(line, comments=True, posix=True)
        except ValueError as exc:
            warnings.append(f"Line {line_number}: {exc}")
            continue
        if not tokens:
            continue
        command = tokens[0]
        if command in {"sh", "bash", "ksh"} and len(tokens) > 1:
            dependencies.append(_dependency("calls_script", tokens[1], line, tokens[2:], condition, line_number, variables))
        elif command == "source" and len(tokens) > 1:
            dependencies.append(_dependency("sources_script", tokens[1], line, tokens[2:], condition, line_number, variables))
        elif command == "." and len(tokens) > 1:
            dependencies.append(_dependency("sources_script", tokens[1], line, tokens[2:], condition, line_number, variables))
        elif command in _CLIENTS:
            target = _sql_target(tokens, line)
            if target:
                dependencies.append(_dependency("executes_sql", target, line, tuple(tokens[1:]), condition, line_number, variables))
            else:
                warnings.append(f"Line {line_number}: SQL client call has no statically resolved file")
        else:
            redirect = re.search(r"(?:<|@)\s*([^\s;&|]+\.sql)\b", line, re.I)
            if redirect:
                dependencies.append(_dependency("executes_sql", redirect.group(1), line, (), condition, line_number, variables))
    return ShellParseResult(tuple(dependencies), variables, tuple(warnings))


def _dependency(kind: str, target: str, expression: str, arguments, condition: str | None, line: int, variables: dict[str, str]) -> ShellDependencySpec:
    resolved, unresolved = _resolve(target, variables)
    item_warnings = (f"Unresolved shell variable in path: {target}",) if unresolved else ()
    return ShellDependencySpec(kind, resolved, expression, tuple(arguments), condition, line, line, "low" if unresolved else "high", item_warnings)


def _resolve(value: str, variables: dict[str, str]) -> tuple[str, bool]:
    unresolved = False

    def replace(match: re.Match[str]) -> str:
        nonlocal unresolved
        name = match.group(1) or match.group(2)
        if name not in variables:
            unresolved = True
            return match.group(0)
        return variables[name]

    return re.sub(r"\$\{([A-Za-z_][\w]*)\}|\$([A-Za-z_][\w]*)", replace, value), unresolved


def _sql_target(tokens: list[str], line: str) -> str | None:
    for flag in ("-f", "-i"):
        if flag in tokens and tokens.index(flag) + 1 < len(tokens):
            return tokens[tokens.index(flag) + 1]
    for token in tokens[1:]:
        if token.startswith("@") and token[1:].lower().endswith(".sql"):
            return token[1:]
    redirect = re.search(r"<\s*([^\s;&|]+\.sql)\b", line, re.I)
    return redirect.group(1) if redirect else None
