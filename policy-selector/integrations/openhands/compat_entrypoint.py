"""Process-local OpenHands MCP Responses schema compatibility fix.

Run with the Python interpreter that has OpenHands installed. The independent
policy-selector server and the installed OpenHands files are not modified.
"""

import json
import sys


def apply_compatibility():
    from openhands.sdk.mcp.tool import MCPToolDefinition, _create_mcp_action_type
    from openhands.sdk.tool import ToolDefinition

    if MCPToolDefinition.to_responses_tool is not ToolDefinition.to_responses_tool:
        return False

    def to_responses_tool(self, add_security_risk_prediction=False, action_type=None):
        if action_type is not None:
            raise ValueError("MCP tool schemas cannot be overridden by the caller")
        return ToolDefinition.to_responses_tool(
            self,
            add_security_risk_prediction=add_security_risk_prediction,
            action_type=_create_mcp_action_type(self.mcp_tool),
        )

    MCPToolDefinition.to_responses_tool = to_responses_tool
    return True


def self_test():
    from mcp.types import Tool
    from openhands.sdk.mcp.definition import MCPToolAction
    from openhands.sdk.mcp.tool import MCPToolDefinition

    tool = MCPToolDefinition.model_construct(
        description="Select policies", action_type=MCPToolAction,
        mcp_tool=Tool(name="compat_task_probe", inputSchema={
            "type": "object", "properties": {"task": {"type": "string"}}, "required": ["task"]}))
    before = tool.to_responses_tool()["parameters"]
    applied = apply_compatibility()
    after = tool.to_responses_tool()["parameters"]
    assert after == tool.to_openai_tool()["function"]["parameters"]
    assert "task" in after["required"] and "data" not in after["properties"]
    assert tool.action_from_arguments({"task": "coding task"}).data == {"task": "coding task"}
    try:
        tool.action_from_arguments({"data": {"task": "coding task"}})
    except ValueError:
        wrapped_rejected = True
    else:
        raise AssertionError("Execution validator unexpectedly accepted wrapped arguments")
    assert apply_compatibility() is False, "Fix should be idempotent"
    print(json.dumps({"applied": applied, "before": before, "after": after,
                      "flat_accepted": True, "wrapped_rejected": wrapped_rejected,
                      "chat_and_responses_schemas_agree": True}, indent=2))


def main():
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return
    applied = apply_compatibility()
    print(f"PECA OpenHands MCP compatibility applied: {applied}", file=sys.stderr, flush=True)
    from openhands_cli.entrypoint import main as openhands_main
    openhands_main()


if __name__ == "__main__":
    main()
