"""ADK agent entry point.

This module defines the root_agent that ADK discovers when running
`adk run workflow_engine` or `adk web`.
"""
from pathlib import Path

from .procedures.registry import ProcedureRegistry
from .agents.router import create_router_agent

# Resolve the procedures directory relative to the project root
_PROJECT_ROOT = Path(__file__).parent.parent
_PROCEDURES_DIR = _PROJECT_ROOT / "procedures"

# Load all procedure definitions
registry = ProcedureRegistry(str(_PROCEDURES_DIR))

# Build the agent tree: router -> [customer_service, fraud_ops, general]
root_agent = create_router_agent(registry)
