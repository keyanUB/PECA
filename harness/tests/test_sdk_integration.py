"""Run the installed SDK loop with scripted steps; no API calls or Docker."""
from pathlib import Path
import json
import signal
import subprocess

import pytest

PYTHON = Path.home() / ".local/share/uv/tools/openhands/bin/python"
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(not PYTHON.exists(), reason="OpenHands SDK unavailable")
def test_real_sdk_iteration_boundary_and_error_propagation():
    code = '''
import tempfile
from unittest.mock import patch
from openhands.sdk import Agent, Conversation, LLM
from openhands.sdk.conversation.state import ConversationExecutionStatus as Status
from openhands.sdk.conversation.exceptions import ConversationRunError
from harness.adapters.repository_sdk import MeasuredAgent, run_bounded

for finish_on, expected in [(1, "finished"), (2, "finished"), (None, "iteration_limit")]:
    calls = []
    def step(self, conversation, **kwargs):
        calls.append(1)
        if len(calls) == finish_on:
            conversation.state.execution_status = Status.FINISHED
    with tempfile.TemporaryDirectory() as work, patch.object(Agent, "step", step):
        agent = MeasuredAgent(llm=LLM(model="openai/gpt-5.4-mini", api_key="unused"), step_limit=2)
        conversation = Conversation(agent=agent, workspace=work, max_iteration_per_run=3)
        conversation.send_message("Offline iteration probe")
        assert run_bounded(conversation) == expected
        assert len(calls) == agent._step_calls == (finish_on or 2)
        assert {"finish", "think"} <= set(agent.tools_map)
        if finish_on:
            assert conversation.state.execution_status == Status.FINISHED

with tempfile.TemporaryDirectory() as work, patch.object(Agent, "step", side_effect=ValueError("test error")):
    agent = MeasuredAgent(llm=LLM(model="openai/gpt-5.4-mini", api_key="unused"), step_limit=2)
    conversation = Conversation(agent=agent, workspace=work, max_iteration_per_run=3)
    conversation.send_message("Offline error probe")
    try:
        run_bounded(conversation)
    except ConversationRunError:
        pass
    else:
        raise AssertionError("SDK errors must not be treated as budget exhaustion")
'''
    completed = subprocess.run([str(PYTHON), "-c", code], cwd=ROOT,
                               capture_output=True, text=True, timeout=45)
    assert completed.returncode == 0, completed.stderr[-4000:]


@pytest.mark.skipif(not PYTHON.exists(), reason="OpenHands SDK unavailable")
@pytest.mark.parametrize('killed', [False, True])
def test_real_sdk_usage_checkpoint_survives_sigkill_before_step_returns(tmp_path, killed):
    output = tmp_path / 'sdk'
    request = tmp_path / 'request.json'
    request.write_text(json.dumps({'workspace': str(tmp_path), 'output': str(output),
                                   'image': 'synthetic', 'model': 'openai/gpt-5.4-mini',
                                   'max_iterations': 2, 'prompt': 'Synthetic usage test'}))
    code = '''
import os, sys, signal
os.environ['OPENAI_API_KEY'] = 'unused-offline-test'
os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
from unittest.mock import patch
from openhands.sdk import Agent, TextContent
from openhands.sdk.event import MessageEvent
from openhands.sdk.llm import Message
from openhands.sdk.conversation.state import ConversationExecutionStatus as Status
from harness.adapters import repository_sdk as worker

killed = sys.argv[2] == 'True'
request = sys.argv[1]
class FakeSandbox:
    image_id = 'synthetic'
    def __init__(self, *args, **kwargs): pass
    def __enter__(self): return self
    def __exit__(self, *args): pass

def step(self, conversation, **kwargs):
    self.llm.metrics.add_cost(.125)
    self.llm.metrics.add_token_usage(prompt_tokens=10, completion_tokens=5, cache_read_tokens=0,
                                    cache_write_tokens=0, context_window=100, response_id='synthetic')
    kwargs['on_event'](MessageEvent(source='agent', llm_message=Message(
        role='assistant', content=[TextContent(text='Synthetic response, no API call.')])) )
    if killed:
        os.kill(os.getpid(), signal.SIGKILL)
    conversation.state.execution_status = Status.FINISHED

sys.argv = ['worker', request]
with patch.object(worker, 'Sandbox', FakeSandbox), patch.object(Agent, 'step', step):
    worker.main()
'''
    completed = subprocess.run([str(PYTHON), '-c', code, str(request), str(killed)], cwd=ROOT,
                               capture_output=True, text=True, timeout=45)
    assert completed.returncode == (-signal.SIGKILL if killed else 0), completed.stderr[-4000:]
    checkpoint = json.loads((output / 'usage.json').read_text())
    assert checkpoint['metrics']['accumulated_cost'] == .125
    assert checkpoint['metrics']['accumulated_token_usage']['prompt_tokens'] == 10
    assert checkpoint['usage_complete'] is False
    if killed:
        assert not (output / 'result.json').exists()
    else:
        terminal = json.loads((output / 'result.json').read_text())
        assert terminal['metrics']['accumulated_cost'] == .125
        assert terminal['usage_complete'] is True
