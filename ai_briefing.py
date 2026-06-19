"""
ai_briefing.py — MacroPulse India, Day 10 (AI Briefing Engine)

Narrates the deterministic payload from brief_facts.py into an analyst briefing.

Two paths:
  - render_template(payload): deterministic prose, no API. Always works, fully reproducible.
  - render_llm(payload): optional Anthropic (Claude) narration under a STRICT grounding
    prompt — narrate only the supplied facts, invent no numbers — with graceful fallback
    to the template if the SDK/key is missing or the call fails.

The engine owns the numbers; the LLM owns only the language. That boundary is what makes
the briefing trustworthy rather than a confident fabrication.

Env: ANTHROPIC_API_KEY (optional), BRIEFING_MODEL (optional), USE_LLM=1 to try the LLM path.
"""
from __future__ import annotations

import json
import logging
import os
import sys

from brief_facts import assemble

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("ai_briefing")

GROUNDING_PROMPT = """You are a macroeconomic analyst writing a concise briefing for a \
business decision-maker. Narrate ONLY the facts in the JSON payload below into clear, \
professional prose.

Rules:
- Do NOT invent, infer, or alter any numbers. Use only values present in the payload.
- Lead with the supplied headline, then the macro environment (flag any outsized_factors).
- Present sectors in the given order (already sorted by evidence, then magnitude). For each, \
narrate the implied % move and the largest driver's contribution share and significance.
- If a sector is absent from the rankings, that means no statistically significant exposure \
to the relevant factors — state this plainly; never imply missing data.
- Surface the evidence labels and the caveats. Be explicit that this is decision support, \
not a market forecast.
- Structure: headline, macro environment, current sector pressure, notable sensitivities, the \
scenario (if present), then caveats. Keep it tight.

PAYLOAD:
{payload}
"""


def render_template(p) -> str:
    ms = p["macro_state"]
    L = [f"# MacroPulse India — Analyst Briefing (as of {p['asof']})", "",
         f"> {p['headline']}", "",
         "## Macro environment",
         f"- CPI: {ms.get('CPI_chg', 0.0):+.2%} MoM",
         f"- IIP: {ms.get('IIP_chg', 0.0):+.2%} MoM",
         f"- Unemployment: {ms.get('Unemployment_chg', 0.0):+.2f}pp"]
    for o in p["outsized_factors"]:
        L.append(f"- ⚠ {o['factor']} is unusually large ({o['value']:+.2%}, {o['z']:+.1f}σ) and "
                 f"dominates the panel — verify it isn't a base/seasonal artifact.")

    L += ["", "## Current sector pressure (decision support, not a forecast)",
          "_Implied daily return; ordered by strength of evidence, then magnitude._", ""]
    if p["active_sectors"]:
        for s in p["active_sectors"]:
            L.append(f"- **{s['sector']}** — {s['direction']} {s['implied_pct']:+.2f}%  "
                     f"[{s['evidence']} evidence]")
            for d in s["drivers"]:
                L.append(f"    - {d['factor']}: {d['contribution_pct']:+.2f}% "
                         f"({d['share']:.0%} of move; β={d['beta']:+.3f}, p={d['pvalue']:.3f}{d['stars']})")
    else:
        L.append("- No sector shows significant exposure to the current macro state.")
    if p["no_exposure_sectors"]:
        L += ["", f"_No significant exposure to current factors: "
                  f"{', '.join(p['no_exposure_sectors'])}._"]

    L += ["", "## Notable significant sensitivities"]
    if p["significant_sensitivities"]:
        for s in p["significant_sensitivities"]:
            L.append(f"- {s['sector']} ~ {s['factor']}: β = {s['beta']:+.4f} "
                     f"(p = {s['pvalue']:.3f}{s.get('stars', '')})")
    else:
        L.append("- None cleared the significance threshold at this sample size.")

    if p["scenario"]:
        sc = p["scenario"]
        L += ["", f"## Scenario — {sc['name']}  ({sc['shocks']})"]
        if sc["results"]:
            for r in sc["results"]:
                sec = r.get("sector", r.get("asset"))
                L.append(f"- {sec}: {r['direction']} ({r['response']:+.4f}), "
                         f"driver {r.get('dominant_factor')}, confidence {r.get('confidence')}")
        else:
            L.append("- No statistically significant sector responses under this scenario.")

    L += ["", "## Caveats"] + [f"- {c}" for c in p["caveats"]]
    return "\n".join(L)


def render_llm(p, model=None):
    try:
        import anthropic
    except ImportError:
        log.warning("anthropic SDK not installed — falling back to template.")
        return None
    if not os.getenv("ANTHROPIC_API_KEY"):
        log.warning("ANTHROPIC_API_KEY not set — falling back to template.")
        return None
    try:
        client = anthropic.Anthropic()
        model = model or os.getenv("BRIEFING_MODEL", "claude-sonnet-4-6")  # set to a current model
        msg = client.messages.create(
            model=model, max_tokens=1200,
            messages=[{"role": "user", "content": GROUNDING_PROMPT.format(payload=json.dumps(p, indent=2))}])
        return "".join(blk.text for blk in msg.content if getattr(blk, "type", None) == "text")
    except Exception as e:
        log.warning("LLM narration failed (%s) — falling back to template.", e)
        return None


def brief(scenario_name=None, use_llm=False, freq="daily") -> str:
    payload = assemble(scenario_name=scenario_name, freq=freq)
    if use_llm:
        text = render_llm(payload)
        if text:
            return text
    return render_template(payload)


def main() -> int:
    use_llm = os.getenv("USE_LLM") == "1"
    scenario = os.getenv("BRIEF_SCENARIO") or None
    print(brief(scenario_name=scenario, use_llm=use_llm))
    return 0


if __name__ == "__main__":
    sys.exit(main())