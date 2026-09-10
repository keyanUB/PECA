from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from policy_selector.catalog import Catalog
from policy_selector.models import CodeFile, Decision, Evidence, PreviousPolicy, Selection
from policy_selector.selector import Selector


def response(selection):
    return SimpleNamespace(output_parsed=selection, status="completed", model="gpt-5.6-luna",
                           id="test-response", usage=None)


def decision(policy_id, quote="Use SQLite"):
    return Decision(policy_id=policy_id, rationale="User input reaches SQL", guidance="Bind parameters",
                    evidence=[Evidence(source="task", quote=quote)], assessment="applicable")


@pytest.mark.asyncio
async def test_output_uses_catalog_text_and_tracks_model():
    catalog = Catalog()
    policy_id = next(iter(catalog.policies))
    output = Selection(summary="SQL task", selected=[decision(policy_id)], removed=[], limitations=[])
    client = SimpleNamespace(responses=SimpleNamespace(parse=AsyncMock(return_value=response(output))))
    result = await Selector(catalog, client).select("task", "Use SQLite")
    assert result["selected"][0]["policy"] == catalog.policies[policy_id].model_dump()
    assert result["response_model"] == "gpt-5.6-luna"
    assert client.responses.parse.call_args.kwargs["store"] is False


def test_unknown_policy_and_fabricated_evidence_rejected():
    selector = Selector(Catalog())
    output = Selection(summary="", selected=[decision("invented")], removed=[], limitations=[])
    with pytest.raises(ValueError, match="unknown"):
        selector.validate(output, "Use SQLite", [], set(), "task")
    output.selected[0] = decision(next(iter(selector.catalog.policies)), "nonexistent code")
    with pytest.raises(ValueError, match="evidence"):
        selector.validate(output, "Use SQLite", [], set(), "task")


def test_refinement_cannot_silently_drop_previous_policies():
    selector = Selector(Catalog())
    previous_id = next(iter(selector.catalog.policies))
    output = Selection(summary="", selected=[], removed=[], limitations=[])
    with pytest.raises(ValueError, match="every previous"):
        selector.validate(output, "Use SQLite", [], {previous_id}, "refinement")


@pytest.mark.asyncio
async def test_unknown_previous_rejected_before_api():
    client = SimpleNamespace(responses=SimpleNamespace(parse=AsyncMock()))
    with pytest.raises(ValueError, match="unknown policy"):
        await Selector(Catalog(), client).select("refinement", "Use SQLite",
            [CodeFile(path="app.py", content="pass")], [PreviousPolicy(policy_id="invented")])
    client.responses.parse.assert_not_called()


@pytest.mark.asyncio
async def test_incomplete_response_rejected():
    incomplete = response(None)
    incomplete.status = "incomplete"
    client = SimpleNamespace(responses=SimpleNamespace(parse=AsyncMock(return_value=incomplete)))
    with pytest.raises(RuntimeError, match="incomplete"):
        await Selector(Catalog(), client).select("task", "Use SQLite")


@pytest.mark.asyncio
async def test_one_repair_attempt_for_invalid_evidence():
    catalog = Catalog()
    pid = next(iter(catalog.policies))
    invalid = Selection(summary="", selected=[decision(pid, "invented quote")], removed=[], limitations=[])
    valid = Selection(summary="", selected=[decision(pid)], removed=[], limitations=[])
    parse = AsyncMock(side_effect=[response(invalid), response(valid)])
    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    result = await Selector(catalog, client).select("task", "Use SQLite")
    assert len(result["attempts"]) == 2
    assert "validation_feedback" in parse.call_args.kwargs["input"]


@pytest.mark.asyncio
async def test_repair_is_bounded_and_never_accepts_invalid_output():
    catalog = Catalog()
    invalid = Selection(summary="", selected=[decision(next(iter(catalog.policies)), "invented")],
                        removed=[], limitations=[])
    parse = AsyncMock(return_value=response(invalid))
    with pytest.raises(ValueError, match="evidence"):
        await Selector(catalog, SimpleNamespace(responses=SimpleNamespace(parse=parse))).select("task", "Use SQLite")
    assert parse.call_count == 2
