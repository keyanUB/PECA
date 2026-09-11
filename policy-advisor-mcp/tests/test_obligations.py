import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from policy_selector.catalog import Catalog
from policy_selector.models import (AdvisorySelection, ContextClaim, Evidence, Obligation, ProposedCheck,
                                    SecurityContext, SourceReferencedAdvisorySelection)
from policy_selector.selector import Selector
from test_selector import decision, response


def fixture():
    catalog = Catalog()
    pid = next(iter(catalog.policies))
    obligation = Obligation(id="sql.input", requirement="Bind untrusted input", policy_ids=[pid],
        context_ids=["input"], applicability_conditions=["Input is untrusted"],
        evidence=[Evidence(source="task", quote="Use SQLite")],
        suggested_checks=[ProposedCheck(method="behavioral_test", description="Try SQL injection",
                                        expected_evidence="No unintended rows returned")], limitations=[])
    output = AdvisorySelection(summary="SQL", selected=[decision(pid)], removed=[], limitations=[],
                               obligations=[obligation])
    context = SecurityContext(untrusted_inputs=[ContextClaim(id="input", statement="Client input",
                                                            status="assumed")])
    return catalog, output, context


@pytest.mark.asyncio
async def test_context_and_advisory_status_are_preserved():
    catalog, output, context = fixture()
    parse = AsyncMock(return_value=response(output))
    result = await Selector(catalog, SimpleNamespace(responses=SimpleNamespace(parse=parse))).select(
        "task", "Use SQLite", security_context=context)
    assert result["obligations"][0]["verification_status"] == "unverified"
    assert result["obligations"][0]["advisory"] is True
    assert result["security_context"]["untrusted_inputs"][0]["status"] == "assumed"
    assert parse.call_args.kwargs["text_format"] is SourceReferencedAdvisorySelection
    assert json.loads(parse.call_args.kwargs["input"])["security_context"] == context.model_dump()


@pytest.mark.parametrize("mutation,match", [
    ("policy", "unselected"), ("context", "unknown context"),
    ("evidence", "Evidence"), ("duplicate", "Duplicate")])
def test_invalid_obligations_rejected(mutation, match):
    catalog, output, context = fixture()
    if mutation == "policy": output.obligations[0].policy_ids = ["invented"]
    if mutation == "context": output.obligations[0].context_ids = ["invented"]
    if mutation == "evidence": output.obligations[0].evidence[0].quote = "invented"
    if mutation == "duplicate": output.obligations.append(output.obligations[0])
    with pytest.raises(ValueError, match=match):
        Selector(catalog).validate_obligations(output, {"task": "Use SQLite"}, context)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["unsupported", "bad_quote", "duplicate", "oversize"])
async def test_invalid_context_rejected_before_api(kind):
    catalog, _, context = fixture()
    claim = context.untrusted_inputs[0]
    if kind == "unsupported": claim.status = "supported"
    if kind == "bad_quote": claim.evidence = [Evidence(source="task", quote="invented")]
    if kind == "duplicate": context.assets = [claim]
    if kind == "oversize":
        context.assets = [ContextClaim(id=str(i), statement="x" * 2000, status="unknown") for i in range(15)]
    parse = AsyncMock()
    with pytest.raises(ValueError):
        await Selector(catalog, SimpleNamespace(responses=SimpleNamespace(parse=parse))).select(
            "task", "Use SQLite", security_context=context)
    parse.assert_not_called()


@pytest.mark.asyncio
async def test_obligation_validation_uses_bounded_repair():
    catalog, valid, context = fixture()
    invalid = valid.model_copy(deep=True)
    invalid.obligations[0].policy_ids = ["invented"]
    parse = AsyncMock(side_effect=[response(invalid), response(valid)])
    result = await Selector(catalog, SimpleNamespace(responses=SimpleNamespace(parse=parse))).select(
        "task", "Use SQLite", security_context=context)
    assert len(result["attempts"]) == 2


@pytest.mark.asyncio
async def test_obligations_can_be_requested_without_context():
    catalog, output, _ = fixture()
    output.obligations[0].context_ids = []
    parse = AsyncMock(return_value=response(output))
    result = await Selector(catalog, SimpleNamespace(responses=SimpleNamespace(parse=parse))).select(
        "task", "Use SQLite", propose_obligations=True)
    assert result["security_context"] is None
    assert result["obligations"]
