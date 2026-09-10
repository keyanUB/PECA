"""Run with OpenHands' Python. The only agent tool executes inside Docker."""
import argparse
import inspect
import json
import os
from pathlib import Path
import sys

# Explicit trusted harness import; no candidate directories enter sys.path.
sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from harness.sandbox import Sandbox
from harness.adapters.repository import system_prompt


from pydantic import Field, PrivateAttr
from openhands.sdk import Action, Observation, Agent, AgentContext, Conversation, TextContent, Tool, ToolDefinition
from openhands.sdk.llm import LLM
from openhands.sdk.tool import ToolExecutor, register_tool


class MeasuredAgent(Agent):
    _step_calls: int = PrivateAttr(default=0)

    @property
    def prompt_dir(self):
        # SDK defaults derive this from the subclass module, which has no templates.
        return str(Path(inspect.getfile(Agent)).parent / "prompts")

    def step(self, *args, **kwargs):
        self._step_calls += 1
        return super().step(*args, **kwargs)


class ShellAction(Action):
    command: str = Field(max_length=20_000, description="POSIX shell command inside the isolated repository container")

class ShellObservation(Observation):
    output: str
    exit_code: int

    @property
    def to_llm_content(self):
        return [TextContent(text=f"exit={self.exit_code}\n{self.output}")]

class Executor(ToolExecutor):
    def __init__(self, sandbox, output):
        self.sandbox, self.output = sandbox, output

    def __call__(self, action, conversation=None):
        result = self.sandbox.execute(action.command, timeout=60)
        with (self.output / "commands.jsonl").open("a") as f:
            f.write(json.dumps({"command": action.command, **result}) + "\n")
        return ShellObservation(output=result["output"][-40_000:], exit_code=result["exit_code"])

class RepositoryShell(ToolDefinition):
    @classmethod
    def create(cls, conv_state, **params):
        return [cls(description="Read, edit, build and test repository files via a shell in /workspace. "
                    "No network or host filesystem is available. Use heredocs to write files.",
                    action_type=ShellAction, observation_type=ShellObservation, executor=Executor(ACTIVE_SANDBOX, ACTIVE_OUTPUT))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path)
    args = parser.parse_args()
    req = json.loads(args.request.read_text())
    output = Path(req["output"])
    output.mkdir(parents=True, exist_ok=False)

    sandbox_instance = Sandbox(req["image"], Path(req["workspace"]))
    if "container_name" in req:
        sandbox_instance.name = req["container_name"]
    with sandbox_instance as sandbox:
        global ACTIVE_SANDBOX, ACTIVE_OUTPUT
        ACTIVE_SANDBOX, ACTIVE_OUTPUT = sandbox, output
        register_tool(RepositoryShell.name, RepositoryShell)
        agent = MeasuredAgent(llm=LLM(model=req["model"], api_key=os.environ["OPENAI_API_KEY"], usage_id="peca-repository"),
                      tools=[Tool(name=RepositoryShell.name)], tool_concurrency_limit=1,
                      agent_context=AgentContext(system_message_suffix=system_prompt(req.get("language", "C/C++"))))
        def record(event):
            with (output / "events.jsonl").open("a") as f:
                f.write(event.model_dump_json() + "\n")
        conversation = Conversation(agent=agent, workspace=str(output), callbacks=[record], max_iteration_per_run=req.get("max_iterations", 20))
        conversation.send_message(req["prompt"])
        try:
            conversation.run()
        finally:
            metrics = conversation.conversation_stats.get_combined_metrics()
            result = {"execution_status": str(conversation.state.execution_status.value),
                      "image_id": sandbox.image_id, "tool_surface": [RepositoryShell.name],
                      "agent_step_calls": agent._step_calls,
                      "metrics": metrics.model_dump(mode="json")}
            (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
