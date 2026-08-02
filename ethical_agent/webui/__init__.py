"""Local-only web interface for ethical_agent (chat screen; audit screen
comes in a later change). Server-side only: everything here talks to the
shared ethical_agent pipeline exactly like the CLI does, never reimplementing
guardrail logic. See ethical_agent/webui/server.py for the entry point.
"""
