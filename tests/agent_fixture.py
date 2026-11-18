"""Legacy scripted loop for isolated business-tool unit tests; never production selection."""
from unittest.mock import patch
from desk_companion.chat.assistant import build_agent as _build_product


def build_tool_fixture(host):
    from atlas import Agent
    with patch('desk_companion.pi_runtime.chat_agent.PiChatAgent',Agent):
        return _build_product(host)
