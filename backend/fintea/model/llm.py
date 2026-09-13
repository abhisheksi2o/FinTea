"""Optional AI commentary on the built model (requires ANTHROPIC_API_KEY).

The rules-based feedback in ``feedback.py`` always runs. When an Anthropic API
key is configured, this module asks Claude for an analyst-style qualitative
review of the model's outputs and assumptions. Every number Claude sees comes
from the evaluated workbook, so the commentary is grounded in the model.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from .. import config
from .builder import ModelResult

SYSTEM = (
    "You are a senior equity research analyst reviewing a DCF and three-statement model built by a junior. "
    "You receive the model's key outputs, assumptions and rule-based checks as JSON. Write a concise, critical "
    "qualitative review: (1) the two or three assumptions that matter most and whether they look aggressive, "
    "conservative or reasonable given the history; (2) what the valuation gap versus the market price most likely "
    "reflects; (3) specific changes you would make and what evidence you would seek. Use plain language, refer to "
    "concrete numbers from the JSON, and do not invent data that is not in the JSON. Respond with 5-8 short "
    "paragraphs or bullet points, no headings, no preamble."
)


def _payload(res: ModelResult) -> Dict[str, Any]:
    A = res.assumptions
    return {
        "company": res.summary["company"], "symbol": res.summary["symbol"], "currency": res.summary["currency"],
        "units": res.summary["units"], "source": res.summary["source"],
        "summary": {k: v for k, v in res.summary.items() if k not in ("labels", "error_cells")},
        "assumptions": {s["key"]: {"value": s["value"], "basis": s["basis"]} for s in A.to_json()["items"]},
        "checks": [{"check": q["check"], "status": q["status"], "value": q["value"]} for q in res.feedback["quantitative"]],
        "rules_based_narrative": res.feedback["qualitative"],
    }


def ai_commentary(res: ModelResult) -> Dict[str, Any]:
    import anthropic

    client = anthropic.Anthropic()
    payload = json.dumps(_payload(res), default=str)
    try:
        response = client.beta.messages.create(
            model=config.LLM_MODEL,
            max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM,
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": f"Model JSON:\n{payload}"}],
        )
    except anthropic.BadRequestError:
        # older models / platforms may not accept the fallback parameter: retry without it
        response = client.messages.create(
            model=config.LLM_MODEL, max_tokens=4000, system=SYSTEM,
            messages=[{"role": "user", "content": f"Model JSON:\n{payload}"}],
        )
    if response.stop_reason == "refusal":
        return {"status": "refused", "model": response.model, "text": ""}
    text = "\n".join(b.text for b in response.content if b.type == "text").strip()
    return {"status": "ok", "model": response.model, "text": text}
