"""Run with OpenHands' Python interpreter to reproduce its MCP schema mismatch."""

import json

from mcp.types import Tool
from openhands.sdk.mcp.definition import MCPToolAction
from openhands.sdk.mcp.tool import MCPToolDefinition


def main():
    tool = MCPToolDefinition.model_construct(
        description="Select policies", action_type=MCPToolAction,
        mcp_tool=Tool(name="select_for_task", inputSchema={
            "type": "object", "properties": {"task": {"type": "string"}}, "required": ["task"]}))
    result = {
        "chat_completions_schema": tool.to_openai_tool()["function"]["parameters"],
        "responses_schema": tool.to_responses_tool()["parameters"],
    }
    for label, arguments in [("flat", {"task": "a coding task"}),
                             ("wrapped", {"data": {"task": "a coding task"}})]:
        try:
            tool.action_from_arguments(arguments)
            result[label + "_accepted"] = True
        except ValueError:
            result[label + "_accepted"] = False
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
