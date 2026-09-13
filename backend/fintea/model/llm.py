"""Optional AI commentary on the built model (requires ANTHROPIC_API_KEY).

The rules-based feedback in ``feedback.py`` always runs. When an Anthropic API
key is configured, this module asks Claude for an analyst-style qualitative
review of the model's outputs and assumptions. Every number Claude sees comes
from the evaluated workbook, so the commentary is grounded in the model. The
same prompt and input shape are used by the static site (browser-side, with the
visitor's own key) so both paths produce comparable commentary.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional

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


def payload_from_parts(summary: Dict[str, Any], assumptions_json: Dict[str, Any], feedback: Dict[str, Any]) -> Dict[str, Any]:
    """The exact JSON Claude reviews (shared shape with the browser implementation)."""
    return {
        "company": summary["company"], "symbol": summary["symbol"], "currency": summary["currency"],
        "units": summary["units"], "source": summary["source"],
        "summary": {k: v for k, v in summary.items() if k not in ("labels", "error_cells")},
        "assumptions": {s["key"]: {"value": s["value"], "basis": s["basis"]} for s in assumptions_json["items"]},
        "checks": [{"check": q["check"], "status": q["status"], "value": q["value"]} for q in feedback["quantitative"]],
        "rules_based_narrative": feedback["qualitative"],
    }


def _payload(res: ModelResult) -> Dict[str, Any]:
    return payload_from_parts(res.summary, res.assumptions.to_json(), res.feedback)


def commentary_key(summary: Dict[str, Any]) -> str:
    """Cache key: commentary is regenerated only when the valuation picture changes materially."""
    up = summary.get("upside")
    parts = [summary.get("symbol"), summary.get("base_year"),
             None if up is None else round(up / 0.05) * 0.05,          # 5pp buckets of upside
             None if summary.get("wacc") is None else round(summary["wacc"], 3),
             summary.get("overall_status"), summary.get("n_flag"), summary.get("n_fail"), config.LLM_MODEL]
    return hashlib.sha1(json.dumps(parts, default=str).encode()).hexdigest()[:16]


def ai_commentary(res: ModelResult, client: Optional[Any] = None) -> Dict[str, Any]:
    import anthropic

    client = client or anthropic.Anthropic()
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
        return {"status": "refused", "model": response.model, "text": "", "key": commentary_key(res.summary)}
    text = "\n".join(b.text for b in response.content if b.type == "text").strip()
    return {"status": "ok", "model": response.model, "text": text, "key": commentary_key(res.summary)}
