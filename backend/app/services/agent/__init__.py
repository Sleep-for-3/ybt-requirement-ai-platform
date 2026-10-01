"""Governed Agent orchestration layer.

Module map:

* ``state_machine`` — pure status vocabulary + legal transitions.
* ``planner`` — constrained plan generation (deterministic + LLM refinement).
* ``runtime`` — durable execution, retry, replan, human gates, artifacts.
* ``tools`` — the controlled tool registry and the registered capabilities.
* ``observability`` — agent-level metrics derived from the durable records.
"""
