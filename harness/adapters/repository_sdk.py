"""Run with OpenHands' Python. The only agent tool executes inside Docker."""
import argparse
import inspect
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys

# Explicit trusted harness import; no candidate directories enter sys.path.
sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from harness.sandbox import Sandbox
from harness.adapters.repository import system_prompt, execute_repository_command
from harness.adapters.usage import atomic_json
from harness.policy_delivery import visible_command_output


from pydantic import Field, PrivateAttr
from openhands.sdk import Action, Observation, Agent, AgentContext, Conversation, TextContent, Tool, ToolDefinition
from openhands.sdk.llm import LLM
from openhands.sdk.tool import ToolExecutor, register_tool
from openhands.sdk.conversation.exceptions import ConversationRunError


class StepBudgetExceeded(RuntimeError):
    """Raised before an extra SDK step can make another model/tool call."""


class MeasuredAgent(Agent):
    _step_calls: int = PrivateAttr(default=0)
    _usage_checkpoint = PrivateAttr(default=None)
    step_limit: int = Field(default=500, ge=1)

    @property
    def prompt_dir(self):
        # SDK defaults derive this from the subclass module, which has no templates.
        return str(Path(inspect.getfile(Agent)).parent / "prompts")

    def step(self, *args, **kwargs):
        if self._step_calls >= self.step_limit:
            raise StepBudgetExceeded("PECA agent step budget exhausted")
        self._step_calls += 1
        try:
            return super().step(*args, **kwargs)
        finally:
            if self._usage_checkpoint is not None:
                self._usage_checkpoint()


def run_bounded(conversation):
    try:
        conversation.run()
    except ConversationRunError as exc:
        if isinstance(exc.original_exception, StepBudgetExceeded):
            return "iteration_limit"
        raise
    return conversation.state.execution_status.value


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
        result = execute_repository_command(self.sandbox, action.command)
        with (self.output / "commands.jsonl").open("a") as f:
            f.write(json.dumps({"command": action.command, **result}) + "\n")
        return ShellObservation(output=visible_command_output(result), exit_code=result["exit_code"])

class RepositoryShell(ToolDefinition):
    @classmethod
    def create(cls, conv_state, **params):
        return [cls(description="Read, edit, build and test repository files via a shell in /workspace. "
                    "Each call starts a fresh POSIX /bin/sh; cd and exports do not persist. "
                    "No network or host filesystem is available. Use heredocs to write files.",
                    action_type=ShellAction, observation_type=ShellObservation, executor=Executor(ACTIVE_SANDBOX, ACTIVE_OUTPUT))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path)
    args = parser.parse_args()
    req = json.loads(args.request.read_text())
    output = Path(req["output"])
    output.mkdir(parents=True, exist_ok=False)

    sandbox_instance = Sandbox(req["image"], Path(req["workspace"]),
                               control=Path(req["control"]) if req.get("control") else None,
                               writable_paths=req.get("writable_paths"))
    if "container_name" in req:
        sandbox_instance.name = req["container_name"]
    with sandbox_instance as sandbox:
        global ACTIVE_SANDBOX, ACTIVE_OUTPUT
        ACTIVE_SANDBOX, ACTIVE_OUTPUT = sandbox, output
        register_tool(RepositoryShell.name, RepositoryShell)
        iterations = req.get("max_iterations", 20)
        agent = MeasuredAgent(llm=LLM(model=req["model"], api_key=os.environ["OPENAI_API_KEY"], usage_id="peca-repository"),
                      tools=[Tool(name=RepositoryShell.name)], tool_concurrency_limit=1,
                      step_limit=iterations,
                      agent_context=AgentContext(system_message_suffix=system_prompt(req.get("language", "C/C++"))))
        conversation = None
        checkpoint_errors = []
        stop_reason = "error"

        def report(*, terminal=False):
            result = {"execution_status": str(conversation.state.execution_status.value),
                      "stop_reason": stop_reason if terminal else "in_progress",
                      "usage_complete": terminal and stop_reason in ("finished", "stuck", "iteration_limit"),
                      "image_id": sandbox.image_id, "tool_surface": sorted(agent.tools_map),
                      "agent_step_calls": agent._step_calls,
                      "step_limit": iterations, "sdk_version": version("openhands-sdk"),
                      "condenser": type(agent.condenser).__name__ if agent.condenser else None,
                      "model_settings": {k: getattr(agent.llm, k, None) for k in
                                         ("model", "temperature", "top_p", "max_output_tokens",
                                          "reasoning_effort", "seed", "num_retries", "timeout")},
                      "metrics": None, "checkpoint_errors": list(checkpoint_errors)}
            try:
                result["metrics"] = conversation.conversation_stats.get_combined_metrics().model_dump(mode="json")
            except Exception as exc:
                result.update(metrics_error=type(exc).__name__, usage_complete=False)
            return result

        def checkpoint():
            if conversation is None:
                return
            try:
                atomic_json(output / 'usage.json', report())
            except Exception as exc:
                # Observability failure must not manufacture a coding failure.
                error = type(exc).__name__
                if error not in checkpoint_errors:
                    checkpoint_errors.append(error)
                    print(f'Usage checkpoint failed ({error})', file=sys.stderr, flush=True)

        def record(event):
            with (output / "events.jsonl").open("a") as f:
                f.write(event.model_dump_json() + "\n")
            # Action events arrive after the SDK accounts for the LLM response,
            # before potentially slow tools. A later kill preserves this subtotal.
            checkpoint()
        # SDK 1.11.5 overwrites FINISHED with ERROR when the last allowed step
        # finishes. Let its loop observe completion, but guard actual steps above.
        conversation = Conversation(agent=agent, workspace=str(output), callbacks=[record], max_iteration_per_run=iterations + 1)
        agent._usage_checkpoint = checkpoint
        try:
            conversation.send_message(req["prompt"])
            stop_reason = run_bounded(conversation)
        finally:
            checkpoint()
            atomic_json(output / 'result.json', report(terminal=True))


if __name__ == "__main__":
    main()
