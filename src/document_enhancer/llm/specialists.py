"""Restricted Deep Agents specialist factory.

This module supplies a harness boundary only.  Analysis specialists remain in
WT5; callers provide the role prompt, route, schema, and read-only context.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .models import GeminiModelGateway
from .profiles import resolve_route

_FORBIDDEN_TOOL_MARKERS = (
    "shell",
    "exec",
    "command",
    "network",
    "http",
    "browser",
    "search",
    "code",
    "python",
    "file_write",
    "write_file",
)


@dataclass(frozen=True, slots=True)
class SpecialistSpec:
    name: str
    description: str
    system_prompt: str
    route: str = "analysis"
    max_steps: int = 8
    max_input_characters: int = 200_000
    max_subagents: int = 0
    tools: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or not self.name.replace("-", "").replace("_", "").isalnum():
            raise ValueError("specialist name must be a simple stable identifier")
        if self.max_steps < 1:
            raise ValueError("max_steps must be positive")
        if self.max_input_characters < 1:
            raise ValueError("max_input_characters must be positive")
        if self.max_subagents < 0:
            raise ValueError("max_subagents cannot be negative")


@dataclass(frozen=True, slots=True)
class SpecialistBudget:
    max_steps: int
    max_input_characters: int
    max_subagents: int


def _tool_name(tool: Any) -> str:
    if isinstance(tool, Mapping):
        return str(tool.get("name", ""))
    return str(getattr(tool, "name", getattr(tool, "__name__", type(tool).__name__)))


def _validate_tools(tools: Sequence[Any], allow_list: frozenset[str]) -> None:
    for tool in tools:
        name = _tool_name(tool)
        if name not in allow_list:
            raise ValueError(f"specialist tool {name!r} is not in the explicit allow-list")
        lowered = name.lower()
        if any(marker in lowered for marker in _FORBIDDEN_TOOL_MARKERS):
            raise ValueError(f"specialist tool {name!r} is forbidden by the model gateway policy")


def _context_prompt(context: Mapping[str, Any]) -> str:
    """Serialize the supplied virtual context without granting path capabilities."""

    return json.dumps(dict(context), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class RestrictedSpecialist:
    def __init__(
        self,
        *,
        spec: SpecialistSpec,
        gateway: GeminiModelGateway,
        schema: type[Any] | None,
        agent: Any | None,
        budget: SpecialistBudget,
    ) -> None:
        self.name = spec.name
        self.spec = spec
        self.gateway = gateway
        self.schema = schema
        self.agent = agent
        self.budget = budget
        self.invocation_count = 0

    def analyze(self, context: Mapping[str, Any]) -> Any:
        if self.invocation_count >= 1:
            raise RuntimeError(
                "specialist invocation budget exhausted; create a new bounded specialist"
            )
        self.invocation_count += 1
        prompt = _context_prompt(context)
        if len(prompt) > self.budget.max_input_characters:
            raise ValueError("specialist virtual context exceeds its configured input budget")
        if self.agent is not None:
            result = self.agent.invoke(
                {"messages": [{"role": "user", "content": prompt}]},
                config={"recursion_limit": self.budget.max_steps},
            )
            return result
        if self.schema is None:
            raise ValueError("direct specialist mode requires a structured output schema")
        return self.gateway.invoke(
            route=self.spec.route,
            schema=self.schema,
            prompt=prompt,
            stage=self.spec.name,
        ).artifact


class RestrictedSpecialistFactory:
    """Build direct structured specialists or Deep Agents with no host tools."""

    def __init__(
        self,
        gateway: GeminiModelGateway,
        *,
        use_deep_agents: bool = False,
        allowed_tools: Sequence[str] = (),
        max_steps: int = 8,
        max_input_characters: int = 200_000,
        max_subagents: int = 0,
    ) -> None:
        self.gateway = gateway
        self.use_deep_agents = use_deep_agents
        self.allowed_tools = frozenset(allowed_tools)
        self.default_budget = SpecialistBudget(max_steps, max_input_characters, max_subagents)
        _validate_tools((), self.allowed_tools)

    def create(
        self,
        spec: SpecialistSpec,
        *,
        schema: type[Any] | None = None,
        tools: Sequence[Any] = (),
        subagents: Sequence[SpecialistSpec] = (),
    ) -> RestrictedSpecialist:
        if not self.use_deep_agents:
            if tools or subagents:
                raise ValueError("direct specialist mode does not accept tools or subagents")
            return RestrictedSpecialist(
                spec=spec,
                gateway=self.gateway,
                schema=schema,
                agent=None,
                budget=SpecialistBudget(
                    min(spec.max_steps, self.default_budget.max_steps),
                    min(spec.max_input_characters, self.default_budget.max_input_characters),
                    0,
                ),
            )
        _validate_tools(tools, self.allowed_tools)
        if len(subagents) > min(spec.max_subagents, self.default_budget.max_subagents):
            raise ValueError("specialist subagent count exceeds the explicit recursion budget")
        for child in subagents:
            _validate_tools(child.tools, self.allowed_tools)
        from deepagents import create_deep_agent
        from deepagents.backends import StateBackend

        child_configs: Any = [
            {
                "name": child.name,
                "description": child.description,
                "system_prompt": child.system_prompt,
                "tools": list(child.tools),
            }
            for child in subagents
        ]
        agent = create_deep_agent(
            model=self.gateway._build_chat_model(resolve_route(spec.route)),
            tools=list(tools),
            subagents=child_configs,
            backend=StateBackend(),
            permissions=[],
            system_prompt=spec.system_prompt,
            debug=False,
        )
        return RestrictedSpecialist(
            spec=spec,
            gateway=self.gateway,
            schema=schema,
            agent=agent,
            budget=SpecialistBudget(
                min(spec.max_steps, self.default_budget.max_steps),
                min(spec.max_input_characters, self.default_budget.max_input_characters),
                len(child_configs),
            ),
        )


__all__ = [
    "RestrictedSpecialist",
    "RestrictedSpecialistFactory",
    "SpecialistBudget",
    "SpecialistSpec",
]
