"""Tests never reach the network.

Several tests drive engine.run() and the dashboard's live sandbox, and both resolve
their LLM through get_llm(), which picks Claude whenever credentials happen to be in
the environment. The documented way to run this project exports ANTHROPIC_API_KEY, so
without this the suite would quietly bill real money and take minutes instead of
seconds. Tests that want a model pass a stub in explicitly.
"""
import os

os.environ["EWS_LLM"] = "fallback"
