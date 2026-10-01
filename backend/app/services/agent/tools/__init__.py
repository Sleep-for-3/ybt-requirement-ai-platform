"""Registered agent capabilities.

Importing this package registers every builtin tool exactly once. A tool is only
ever reachable through :mod:`app.services.agent.tools.registry`, so the planner
cannot call an unregistered capability even if a model asks for one.
"""
from app.services.agent.tools import ai_skill_tools  # noqa: F401  (import registers the tools)
from app.services.agent.tools import builtin  # noqa: F401  (import registers the tools)
from app.services.agent.tools.registry import (  # noqa: F401
    AgentToolSpec,
    ToolContext,
    ToolExecutionError,
    ToolRegistryError,
    ToolResult,
    get_tool,
    register_tool,
    registered_tools,
    require_tool,
    reset_registry,
    tool_keys,
    tools_visible_for_permissions,
    validate_input,
    validate_spec,
)

__all__ = [
    "AgentToolSpec",
    "ToolContext",
    "ToolExecutionError",
    "ToolRegistryError",
    "ToolResult",
    "get_tool",
    "register_tool",
    "registered_tools",
    "require_tool",
    "reset_registry",
    "tool_keys",
    "tools_visible_for_permissions",
    "validate_input",
    "validate_spec",
]
