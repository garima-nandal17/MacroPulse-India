"""
streamlit_app.py — MacroPulse India · AI macro decision intelligence command center

PRESENTATION LAYER ONLY. Engine, brief_facts.assemble payload, SCENARIOS, SECTOR_LABELS,
schemas and identifiers are untouched — every value rendered comes from the same assemble()
payload the CLI uses. Signal → interpretation → action.

Hierarchy: market ribbon → hero regime → macro evidence (so-what KPIs) → MORNING BRIEF
→ signal quality → winners/losers → scenario intelligence → business interpretation → methodology.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from sensitivity_engine import SensitivityEngine
from impact_panel import SECTOR_LABELS
from whatif_simulator import WhatIfSimulator, SCENARIOS
from brief_facts import assemble
from ai_briefing import render_template, render_llm
from fetch_daily import get_connection

st.set_page_config(page_title="MacroPulse India", page_icon="📈",
                   layout="wide", initial_sidebar_state="collapsed")

GOOD, BAD, WARN, BLUE, ACCENT, MUTED = "#22C55E", "#FF5C7A", "#FBBF24", "#3B82F6", "#00F5D4", "#B7C7D9"
CONF_COLOR = {"High": GOOD, "Medium": WARN, "Low": MUTED}
FACTOR_COLOR = {"CPI_chg": "#FBBF24", "IIP_chg": "#3B82F6", "Unemployment_chg": "#A78BFA"}
CONF_LABEL = {"Strong": "High", "Moderate": "Medium", "Weak": "Low"}
FACTORS = ["CPI_chg", "IIP_chg", "Unemployment_chg"]
FACTOR_LABEL = {"CPI_chg": "Inflation", "IIP_chg": "Industrial production", "Unemployment_chg": "Unemployment"}
SLIDER_RANGE = {"CPI_chg": (-0.02, 0.02, 0.001), "IIP_chg": (-0.10, 0.10, 0.005),
                "Unemployment_chg": (-1.0, 1.0, 0.1)}
INV_LABELS = {v: k for k, v in SECTOR_LABELS.items()}
CHG_OF = {"CPI": "CPI_chg", "IIP": "IIP_chg", "Unemployment": "Unemployment_chg"}
DRIVER_PHRASE = {"CPI_chg": "inflation", "IIP_chg": "industrial output", "Unemployment_chg": "labour conditions"}

SECTOR_ARCHETYPE = {
    "FMCG": "Consumer defensive", "IT": "Export-oriented", "Metals": "Cyclical / industrial",
    "Banks": "Financials", "Auto": "Cyclical / consumer", "Pharma": "Defensive / healthcare",
    "Energy": "Cyclical / commodity", "Realty": "Rate-sensitive / cyclical", "Nifty50": "Broad market",
}
# Curated copy is keyed by (sector, dominant factor) so it is only used when that factor is
# actually driving the sector. Any other case falls back to a driver-accurate generated line —
# so the narrative can never assert a mechanism that isn't operating this regime.
SECTOR_STORY = {
    ("FMCG", "IIP_chg"): "Historically resilient when industrial output weakens.",
    ("IT", "CPI_chg"): "Export earnings benefit as the rupee softens alongside inflation.",
    ("IT", "IIP_chg"): "Export-led demand is relatively insulated from domestic output.",
    ("Metals", "Unemployment_chg"): "Vulnerable as labour conditions soften.",
    ("Metals", "IIP_chg"): "Cyclical demand tracks industrial output.",
    ("Banks", "Unemployment_chg"): "Asset quality tracks the labour market.",
    ("Banks", "IIP_chg"): "Credit demand tracks industrial activity.",
    ("Auto", "IIP_chg"): "Discretionary demand tracks industrial activity.",
    ("Pharma", "IIP_chg"): "Defensive healthcare demand holds through the cycle.",
    ("Energy", "IIP_chg"): "Commodity-linked demand tracks industrial activity.",
}
FACTOR_MOVE = {  # (shock > 0 phrasing, shock < 0 phrasing)
    "CPI_chg": ("inflation rises", "inflation eases"),
    "IIP_chg": ("industrial output strengthens", "industrial output weakens"),
    "Unemployment_chg": ("labour conditions soften", "labour conditions tighten"),
}
SCENARIO_CARDS = [
    ("Stagflation", "Stagflation", "🟥", "Weak growth · sticky inflation"),
    ("Growth Recovery", "Growth surge", "🟩", "Activity re-accelerates"),
    ("Industrial Slowdown", "Industrial slowdown", "🟨", "Manufacturing cools"),
    ("Disinflation", "Disinflation", "🟦", "Inflation eases"),
]
SCENARIO_KEY = {disp: key for disp, key, _, _ in SCENARIO_CARDS}
SCENARIO_INTERP = {
    "Stagflation": "Sticky inflation with weak growth favours defensives with pricing power; rate- and demand-sensitive cyclicals typically lag.",
    "Growth Recovery": "Re-accelerating activity lifts cyclicals and financials; pure defensives may underperform on a relative basis.",
    "Industrial Slowdown": "Cooling manufacturing pressures metals, energy and industrial cyclicals; staples and exporters hold up better.",
    "Disinflation": "Easing inflation supports rate-sensitive and consumption names as financial conditions loosen.",
}


def _rgba(hex_color, a):
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{a})"


# --- AI copilot explanation layer -------------------------------------------
# Custom MacroPulse glyph: a hexagonal "chip" with a pulse waveform + AI spark.
AI_ICON = (
    '<svg class="mp-ai-glyph" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M12 2.2 19.5 6.6 V15.4 L12 19.8 4.5 15.4 V6.6 Z" stroke="#00F5D4" stroke-width="1.3" '
    'stroke-linejoin="round"/>'
    '<path d="M6.6 12 H9 L10.4 8.7 13.4 15 14.8 12 H17.2" stroke="#00F5D4" stroke-width="1.5" '
    'stroke-linecap="round" stroke-linejoin="round"/>'
    '<path d="M18.7 2.6 19.2 4.1 20.7 4.6 19.2 5.1 18.7 6.6 18.2 5.1 16.7 4.6 18.2 4.1 Z" fill="#00F5D4"/>'
    '</svg>'
)

# Each explanation: plain-English meaning, then a business implication (.imp).
# Jargon-free by design — concept → meaning → "so what".
AI_EXPLAIN = {
    "market_pulse":
        "This strip shows how the big markets moved today — the rupee, stock indexes (Nifty, Bank Nifty), "
        "gold, oil, and a 'fear gauge' called India VIX. Green is up, red is down. "
        "<span class='imp'><b>Why it matters:</b> together they reveal the day's mood — when the fear gauge "
        "jumps and stocks fall, markets are nervous; when stocks rise and the rupee firms, they're confident.</span>",
    "kpi":
        "These three gauges describe the economy's health. <b>Inflation (CPI)</b> is how fast prices are "
        "rising. <b>Industrial production (IIP)</b> is how much factories are making — a stand-in for growth. "
        "<b>Unemployment</b> is the share of people who want work but can't find it. ‘YoY’ compares with a year "
        "ago; ‘MoM’ compares with last month. "
        "<span class='imp'><b>So what:</b> read together they tell you if the economy is speeding up or slowing, "
        "and whether prices are under control.</span>",
    "morning_brief":
        "A plain-language summary of the day — what moved in markets, what the wider economy looks like, and "
        "which business sectors the model sees as favoured or exposed right now. "
        "<span class='imp'><b>So what:</b> it's the one-paragraph ‘what's going on and why it matters’ you'd want "
        "before a meeting.</span>",
    "signal_quality":
        "This panel shows how much to trust today's read. It lists how many days of history the analysis used, "
        "how many sector relationships were strong enough to be reliable (not just chance), and an overall "
        "confidence level. It also reports how many signals <b>validated out-of-sample</b> — i.e. still "
        "worked when tested on months the model never trained on. "
        "<span class='imp'><b>Why it matters:</b> more history and more strong, out-of-sample-validated "
        "relationships mean a more dependable signal — it's the ‘how sure are we?’ behind every other number "
        "here.</span>",
    "beneficiaries":
        "Sectors that have historically tended to <b>hold up or gain ground</b> in conditions like today's, based "
        "on how each responds to moves in inflation, factory output, and jobs. The badge shows how strong the "
        "evidence is. <b>Consumer-defensive</b> names (food, household essentials) and <b>export-oriented</b> ones "
        "(software services earning in dollars) often sit here when growth slows. "
        "A <b>Validated OOS</b> chip means the relationship still held when tested on data the model "
        "hadn't seen; <b>Partial</b> means it's promising but not yet confirmed given limited history. "
        "<span class='imp'><b>Important:</b> this is a relative, historical tendency — not a guarantee or a buy "
        "recommendation.</span>",
    "under_pressure":
        "Sectors that have historically tended to <b>struggle</b> in conditions like today's — usually "
        "<b>cyclical</b> businesses (metals, big-ticket goods) whose demand rises and falls with the economy. "
        "These are where weaker demand or higher costs have bitten first. "
        "The <b>Validated / Partial</b> chip shows whether the relationship survived out-of-sample testing. "
        "<span class='imp'><b>Important:</b> like beneficiaries, this is about relative pressure and past patterns, "
        "not a prediction that share prices will fall.</span>",
    "scenario":
        "A ‘what-if’ tool. Pick an economic scenario — or build your own — and see which sectors have historically "
        "benefited or suffered under it. <b>Stagflation</b> = slow growth with high inflation. <b>Growth "
        "recovery</b> = activity speeding up. <b>Industrial slowdown</b> = factories cooling. <b>Disinflation</b> = "
        "price rises easing. "
        "<span class='imp'><b>So what:</b> it lets you stress-test the economy before it happens.</span>",
    "business_interpretation":
        "This turns the data into a few takeaways a manager or investor could actually act on — where strength and "
        "weakness are likely to show up first, and what that implies for positioning. "
        "<span class='imp'><b>So what:</b> it's the bridge from ‘here are the numbers’ to ‘what should I think "
        "about?’</span>",
    "methodology":
        "The ‘show your work’ section. It holds the statistics behind every claim — how strongly each sector moves "
        "with each economic factor, and how confident we are that the link is real rather than coincidence. "
        "It also holds the <b>out-of-sample validation</b> — whether each signal still worked on data the model "
        "never saw. "
        "<span class='imp'><b>Why it matters:</b> you don't need it to use the dashboard, but it's there so the "
        "insights can be checked and trusted.</span>",
}


def regime_explanation(ms):
    """Dynamic plain-English read of the CURRENT regime so it always matches the pills."""
    iip, cpi = ms.get("IIP_chg", 0.0), ms.get("CPI_chg", 0.0)
    growth = "slowing" if iip < 0 else "picking up" if iip > 0 else "roughly flat"
    prices = "still rising" if cpi > 0 else "easing" if cpi < 0 else "broadly steady"
    head = f"Right now the economy looks like it's <b>{growth}</b> while prices are <b>{prices}</b>. "
    if iip < 0 and cpi > 0:
        tail = ("That's a tough mix — demand can weaken even as costs stay high, squeezing businesses and "
                "households at once.<span class='imp'><b>So what:</b> steady ‘everyday essentials’ businesses "
                "have historically held up better than cyclical ones like metals or big-ticket goods here.</span>")
    elif iip > 0 and cpi > 0:
        tail = ("Growth and prices are rising together — often a heating economy.<span class='imp'><b>So what:</b> "
                "cyclical and industrial businesses tend to do relatively well, though high inflation can "
                "eventually bite.</span>")
    elif iip < 0 and cpi < 0:
        tail = ("Both growth and prices are cooling. Lower inflation eases pressure on households, but soft demand "
                "weighs on earnings.<span class='imp'><b>So what:</b> rate-sensitive and consumption names often "
                "fare better as conditions loosen.</span>")
    elif iip > 0 and cpi < 0:
        tail = ("A favourable mix — activity improving while price pressure eases (a ‘soft landing’)."
                "<span class='imp'><b>So what:</b> this backdrop tends to support a broad range of businesses, "
                "especially cyclicals.</span>")
    else:
        tail = ("The signals are mixed.<span class='imp'><b>So what:</b> positioning stays balanced until the "
                "picture sharpens.</span>")
    return head + tail


def ai_panel_html(key, body=None, q="What does this mean?"):
    """Inner HTML for the popover (plain divs/spans survive Streamlit's sanitizer)."""
    text = body if body is not None else AI_EXPLAIN.get(key, "")
    return (f'<div class="mp-ai-head">MacroPulse AI</div>'
            f'<div class="mp-ai-q">{q}</div>'
            f'<div class="mp-ai-a">{text}</div>')


def ai_header(title_html, key, body=None, ratio=(0.84, 0.16)):
    """Render a section heading with a glowing 'Explain' AI popover beside it.
    Falls back to an expander on Streamlit builds without st.popover."""
    c1, c2 = st.columns(list(ratio))
    c1.markdown(title_html, unsafe_allow_html=True)
    has_popover = hasattr(st, "popover")
    container = c2.popover("Explain") if has_popover else c2.expander("Explain")
    with container:
        st.markdown(ai_panel_html(key, body), unsafe_allow_html=True)


CSS = f"""
<style>
.stApp{{background:#0B1020;}}
.block-container{{padding-top:1.4rem;padding-bottom:3rem;max-width:1180px;}}
[data-testid="stHeader"]{{background:transparent;}}
.mp-glass{{background:rgba(17,24,39,.55);border:1px solid rgba(255,255,255,.07);border-radius:20px;
  backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);box-shadow:0 8px 34px rgba(0,0,0,.38);}}
.mp-ribbon{{display:flex;flex-wrap:nowrap;overflow-x:auto;gap:0;align-items:center;margin:.1rem 0 1.4rem;
  padding:11px 6px;background:rgba(17,24,39,.5);border:1px solid rgba(255,255,255,.06);border-radius:14px;
  scrollbar-width:thin;scrollbar-color:#23324a transparent;}}
.mp-ribbon::-webkit-scrollbar{{height:5px;}} .mp-ribbon::-webkit-scrollbar-thumb{{background:#23324a;border-radius:9px;}}
.mp-tick{{font-size:13px;color:#E6EDF6;white-space:nowrap;padding:2px 16px;border-right:1px solid #1c2a40;flex:0 0 auto;}}
.mp-tick:last-child{{border-right:none;}}
.mp-tick b{{color:#7d93ab;font-weight:600;margin-right:7px;font-size:11.5px;letter-spacing:.03em;}}
.mp-asof{{color:#5f7488;font-size:12px;}}
.mp-hero{{display:flex;justify-content:space-between;align-items:center;gap:18px;flex-wrap:wrap;margin:.2rem 0 1.4rem;padding:28px 32px;}}
.mp-eyebrow{{font-size:13px;color:#7d93ab;letter-spacing:.16em;text-transform:uppercase;}}
.mp-name{{font-size:42px;font-weight:800;color:#fff;line-height:1.04;margin:5px 0 2px;letter-spacing:-.01em;}}
.mp-sub{{font-size:12px;color:#93a7be;letter-spacing:.18em;text-transform:uppercase;margin:12px 0 12px;}}
.mp-rpill{{display:inline-block;font-size:22px;font-weight:800;letter-spacing:.02em;text-transform:uppercase;
  padding:11px 20px;border-radius:13px;margin:0 10px 8px 0;animation:rpulse 2.8s ease-in-out infinite;}}
@keyframes rpulse{{0%,100%{{box-shadow:0 0 15px var(--g);}}50%{{box-shadow:0 0 32px var(--g);}}}}
.mp-meta{{text-align:right;min-width:150px;}}
.mp-chip{{display:inline-flex;align-items:center;gap:6px;font-size:12px;padding:5px 12px;border-radius:999px;
  background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.09);color:#cfe0f2;margin:0 0 7px 7px;}}
.mp-kpi{{padding:16px 18px;border-radius:16px;min-height:138px;background:rgba(17,24,39,.5);
  border:1px solid rgba(255,255,255,.06);transition:transform .15s ease,border-color .15s ease;}}
.mp-kpi:hover{{transform:translateY(-2px);border-color:rgba(0,245,212,.35);}}
.mp-kpi .lab{{font-size:12.5px;color:#aebfd2;}}
.mp-kpi .val{{font-size:26px;font-weight:800;margin-top:5px;}}
.mp-kpi .kint{{font-size:13.5px;font-weight:600;margin-top:4px;}}
.mp-kpi .cap{{font-size:11.5px;color:#9aafc4;margin-top:5px;}}
.mp-brief{{padding:28px 34px;margin:.2rem 0 1rem;border-left:3px solid #00F5D4;
  box-shadow:0 8px 34px rgba(0,0,0,.4),0 0 44px rgba(0,245,212,.07);}}
.mp-brief .ttl{{font-size:13px;color:#00F5D4;letter-spacing:.18em;text-transform:uppercase;margin-bottom:14px;}}
.mp-brief .ln{{font-size:23px;line-height:1.5;color:#F2F6FB;font-weight:500;margin:0 0 6px;}}
.mp-brief .conf{{font-size:14px;color:#a3b6c9;margin-top:14px;}}
.mp-brief .lnb{{font-size:18px;line-height:1.55;color:#d7e2ee;margin:0 0 9px;}}
.mp-brief .lnw{{font-size:15px;line-height:1.5;color:#00F5D4;font-weight:500;margin:14px 0 2px;}}
.mp-flag{{display:inline-block;font-size:15px;font-weight:800;letter-spacing:.05em;color:#fff;
  background:linear-gradient(135deg,#FF9933,#0B7A3B);padding:3px 10px;border-radius:7px;margin-right:13px;vertical-align:middle;}}
.mp-sq{{padding:16px 22px;margin-bottom:1rem;display:flex;flex-wrap:wrap;gap:8px 26px;align-items:center;}}
.mp-sq .h{{font-size:12px;color:#a6b8cc;letter-spacing:.16em;text-transform:uppercase;width:100%;margin-bottom:2px;}}
.mp-sq .it{{font-size:13.5px;color:#c7d6e6;display:inline-flex;align-items:center;gap:7px;}}
.mp-sq .ck{{color:#22C55E;}}
.mp-wl{{padding:16px 18px;border-radius:16px;margin-bottom:12px;min-height:140px;background:rgba(17,24,39,.5);
  border:1px solid rgba(255,255,255,.06);transition:transform .15s ease,border-color .15s ease;}}
.mp-wl:hover{{transform:translateY(-2px);border-color:rgba(255,255,255,.14);}}
.mp-wl-h{{display:flex;align-items:center;justify-content:space-between;gap:8px;}}
.mp-wl-name{{font-size:20px;font-weight:700;color:#fff;display:flex;align-items:center;}}
.mp-badge{{font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;padding:3px 10px;border-radius:999px;border:1px solid;}}
.mp-vchip{{display:inline-block;font-size:10.5px;font-weight:700;letter-spacing:.03em;padding:3px 10px;
  border-radius:999px;border:1px solid;}}
.mp-wl-arch{{font-size:12px;letter-spacing:.05em;text-transform:uppercase;color:#a6b8cc;margin:7px 0 7px;}}
.mp-wl-story{{font-size:14px;line-height:1.5;color:#c7d6e6;}}
.dot{{width:11px;height:11px;border-radius:50%;display:inline-block;}}
.sec-h{{font-size:14px;font-weight:700;color:#bccadb;letter-spacing:.14em;text-transform:uppercase;margin:2rem 0 .8rem;}}
.mp-pill{{display:inline-block;font-size:12.5px;padding:5px 12px;border-radius:9px;margin:0 6px 6px 0;
  background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);color:#dce7f3;}}
.stButton>button{{background:rgba(17,24,39,.6);border:1px solid rgba(255,255,255,.09);border-radius:13px;
  color:#E6EDF6;padding:10px 8px;font-weight:600;font-size:13.5px;transition:all .15s ease;height:100%;}}
.stButton>button:hover{{border-color:#00F5D4;color:#fff;box-shadow:0 0 22px rgba(0,245,212,.18);transform:translateY(-2px);}}
[data-testid="stExpander"] details{{background:rgba(17,24,39,.45);border:1px solid rgba(255,255,255,.06);border-radius:14px;overflow:hidden;}}
[data-testid="stExpander"] summary{{background:transparent;color:#bccadb;font-weight:600;}}
[data-testid="stExpander"] summary:hover{{color:#fff;}}
[data-testid="stExpander"] summary p{{color:#bccadb;}}
.stSelectbox label{{color:#DCE7F3 !important;}}
div[data-baseweb="select"]>div{{background:rgba(17,24,39,.65)!important;border-color:rgba(255,255,255,.12)!important;}}
div[data-baseweb="select"] *{{color:#e6edf6!important;}}
ul[role="listbox"]{{background:#111827!important;}}
[data-baseweb="popover"] li{{background:#111827!important;color:#cfe0f2!important;}}
[data-baseweb="popover"] li:hover{{background:#1c2a40!important;}}
h1,h2,h3,h4{{color:#e6edf6;}}
[data-testid="stVerticalBlock"],[data-testid="stElementContainer"]{{overflow:visible;}}
/* ---- AI copilot explanation layer (st.popover based) ---- */
[data-testid="stPopover"] button{{background:rgba(0,245,212,.08) !important;
  border:1px solid rgba(0,245,212,.4) !important;border-radius:999px !important;color:#00F5D4 !important;
  font-size:11px !important;font-weight:700 !important;letter-spacing:.06em !important;
  text-transform:uppercase !important;padding:3px 13px !important;min-height:0 !important;
  line-height:1.5 !important;transition:all .18s ease;}}
[data-testid="stPopover"] button:hover{{background:rgba(0,245,212,.18) !important;
  box-shadow:0 0 16px rgba(0,245,212,.45) !important;color:#bafdf4 !important;
  border-color:rgba(0,245,212,.7) !important;}}
[data-testid="stPopover"] button p{{font-size:11px !important;font-weight:700 !important;
  letter-spacing:.06em !important;}}
[data-testid="stPopover"] button::before{{content:"";display:inline-block;width:14px;height:14px;
  margin-right:7px;vertical-align:-2px;filter:drop-shadow(0 0 4px rgba(0,245,212,.75));
  background:url("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none'><path d='M12 2.2 19.5 6.6V15.4L12 19.8 4.5 15.4V6.6Z' stroke='%2300F5D4' stroke-width='1.4' stroke-linejoin='round'/><path d='M6.6 12H9L10.4 8.7 13.4 15 14.8 12H17.2' stroke='%2300F5D4' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'/><path d='M18.7 2.6 19.2 4.1 20.7 4.6 19.2 5.1 18.7 6.6 18.2 5.1 16.7 4.6 18.2 4.1Z' fill='%2300F5D4'/></svg>") center/contain no-repeat;}}
[data-testid="stPopoverBody"]{{background:linear-gradient(158deg,#0e1a36,#0a1022 72%) !important;
  border:1px solid rgba(0,245,212,.42) !important;border-radius:16px !important;
  box-shadow:0 16px 54px rgba(0,0,0,.6),0 0 38px rgba(0,245,212,.2) !important;
  max-width:560px !important;}}
.mp-ai-head{{display:flex;align-items:center;gap:8px;font-size:11.5px;font-weight:800;letter-spacing:.16em;
  text-transform:uppercase;color:#00F5D4;margin-bottom:10px;text-shadow:0 0 14px rgba(0,245,212,.5);}}
.mp-ai-head::before{{content:"";width:17px;height:17px;flex:0 0 auto;
  filter:drop-shadow(0 0 5px rgba(0,245,212,.8));
  background:url("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none'><path d='M12 2.2 19.5 6.6V15.4L12 19.8 4.5 15.4V6.6Z' stroke='%2300F5D4' stroke-width='1.4' stroke-linejoin='round'/><path d='M6.6 12H9L10.4 8.7 13.4 15 14.8 12H17.2' stroke='%2300F5D4' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'/><path d='M18.7 2.6 19.2 4.1 20.7 4.6 19.2 5.1 18.7 6.6 18.2 5.1 16.7 4.6 18.2 4.1Z' fill='%2300F5D4'/></svg>") center/contain no-repeat;}}
.mp-ai-q{{font-size:13px;font-weight:700;color:#7ff0e4;margin-bottom:7px;}}
.mp-ai-a{{font-size:14.5px;line-height:1.64;color:#EAF2FF;}}
.mp-ai-a b{{color:#fff;font-weight:700;}}
.mp-ai-a .imp{{display:block;margin-top:9px;padding-top:9px;border-top:1px solid rgba(0,245,212,.2);
  color:#9fe9df;font-size:13.5px;}}
.mp-ai-a .imp b{{color:#bafdf4;}}
</style>
"""


@st.cache_resource(show_spinner="Loading engine…")
def get_engine():
    return SensitivityEngine()


@st.cache_data(ttl=600, show_spinner="Assembling decision intelligence…")
def get_payload(alpha, freq, scenario):
    return assemble(scenario_name=scenario, freq=freq, alpha=alpha)


@st.cache_data(ttl=600, show_spinner=False)
def get_validation():
    """Load out-of-sample verdicts. Degrades gracefully if the table isn't built yet."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT asset, factor, prod_significant, verdict, wf_r2, wf_hit, "
                    "holdout_r2, sign_stable, n_wf FROM signal_validation")
        cols = [c[0] for c in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=cols)
        cur.close()
        conn.close()
        for c in ("wf_r2", "wf_hit", "holdout_r2", "sign_stable"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df
    except Exception:
        return pd.DataFrame()


VAL_STYLE = {
    "validated": (GOOD, "✓ Validated OOS"),
    "partial": (WARN, "~ Partial OOS"),
    "in-sample only": (BAD, "✗ In-sample only"),
    "insufficient data": (MUTED, "· Unproven"),
}


def _strip_suffix(a):
    return a.replace("_ret", "").replace("_diff", "")


def val_lookup(vdf):
    """Map validation rows to {(sector_label, factor): verdict}, asset → sector via SECTOR_LABELS."""
    out = {}
    if vdf is None or vdf.empty:
        return out
    for r in vdf.itertuples():
        sec = SECTOR_LABELS.get(r.asset) or SECTOR_LABELS.get(_strip_suffix(r.asset)) or _strip_suffix(r.asset)
        out[(sec, r.factor)] = r.verdict
    return out


def verdict_for(s, vlook):
    """Verdict for a sector's dominant driver (the factor carrying the call)."""
    drv = s.get("drivers", [])
    return vlook.get((s["sector"], drv[0]["factor"])) if drv else None


def validation_chip(verdict):
    if not verdict:
        return ""
    color, label = VAL_STYLE.get(verdict, (MUTED, verdict))
    return (f'<span class="mp-vchip" style="color:{color};border-color:{_rgba(color,.45)};'
            f'background:{_rgba(color,.12)};">{label}</span>')


def regime_pills(ms):
    iip, cpi = ms.get("IIP_chg", 0.0), ms.get("CPI_chg", 0.0)
    pills = [("Contractionary", BAD) if iip < 0 else ("Expansionary", GOOD) if iip > 0 else ("Neutral growth", MUTED)]
    if cpi > 0:
        pills.append(("Inflationary", WARN))
    elif cpi < 0:
        pills.append(("Disinflationary", BLUE))
    html = ""
    for label, color in pills:
        html += (f'<span class="mp-rpill" style="--g:{_rgba(color,.5)};color:{color};'
                 f'border:1px solid {_rgba(color,.45)};background:{_rgba(color,.13)};">{label}</span>')
    return html


def kpi_interp(c):
    ind, yoy, chg = c["indicator"], c.get("yoy"), c.get("model_chg")
    if ind == "CPI":
        if yoy is None:
            return "Inflation trend"
        if yoy > 0.06:
            return "Above RBI comfort zone"
        if yoy >= 0.04:
            return "Upper half of RBI band"
        if yoy >= 0.02:
            return "Within RBI target band"
        return "Below RBI target band"
    if ind == "IIP":
        if chg is None:
            return "Output trend"
        if chg <= -0.02:
            return "Momentum rolling over"
        if chg >= 0.02:
            return "Manufacturing momentum positive"
        return "Output broadly flat"
    if ind == "Unemployment":
        if chg is None:
            return "Labour market"
        if abs(chg) < 0.2:
            return "Labour market stable"
        return "Labour market loosening" if chg > 0 else "Labour market tightening"
    return ""


def _driver_sentence(s, d, ms):
    """Driver-accurate fallback: describe the dominant factor's actual move and whether it
    helps or pressures the sector — never an assumed mechanism."""
    factor = d["factor"]
    shock = (ms or {}).get(factor)
    if shock is None:  # infer sign from contribution and beta if macro state not passed
        shock = d.get("contribution_pct", 0.0) * d.get("beta", 0.0)
    pos, neg = FACTOR_MOVE.get(factor, ("conditions improve", "conditions deteriorate"))
    move = pos if (shock or 0) > 0 else neg
    verb = "Screens positive" if d.get("contribution_pct", 0.0) >= 0 else "Comes under pressure"
    return f"{verb} as {move}."


def sector_story(s, ms=None):
    arch = SECTOR_ARCHETYPE.get(s["sector"], "Sector")
    conf = CONF_LABEL.get(s["evidence"], "—")
    drv = s.get("drivers", [])
    if not drv:
        return arch, "No dominant macro driver this regime.", conf
    d = drv[0]  # dominant contributor
    story = SECTOR_STORY.get((s["sector"], d["factor"])) or _driver_sentence(s, d, ms)
    if conf == "Low":
        story += " A weak, marginal signal — low conviction."
    return arch, story, conf


def wl_card(s, good=True, ms=None, vchip=""):
    arch, story, conf = sector_story(s, ms)
    dot = GOOD if good else BAD
    cc = CONF_COLOR.get(conf, MUTED)
    return (f'<div class="mp-wl"><div class="mp-wl-h">'
            f'<span class="mp-wl-name"><span class="dot" style="background:{dot};box-shadow:0 0 10px {dot};margin-right:10px;"></span>{s["sector"]}</span>'
            f'<span class="mp-badge" style="color:{cc};border-color:{_rgba(cc,.45)};background:{_rgba(cc,.12)};">{conf}</span></div>'
            f'<div class="mp-wl-arch">{arch}</div>'
            f'<div class="mp-wl-story">{story}</div>'
            f'{("<div style=\"margin-top:9px;\">" + vchip + "</div>") if vchip else ""}</div>')


def _kpi_color(ind, chg):
    if chg is None:
        return MUTED
    if ind == "IIP":
        return GOOD if chg > 0 else BAD
    return WARN if chg > 0 else GOOD


def macro_kpi(c, outsized=False):
    ind, chg = c["indicator"], c.get("model_chg")
    color = _kpi_color(ind, chg)
    if c["kind"] == "rate":
        headline = f"{c['level']:.1f}%"
    elif c.get("yoy") is not None:
        headline = f"{c['yoy']:+.1%} YoY"
    else:
        headline = f"index {c['level']:.1f}"
    interp = kpi_interp(c)
    if chg is None:
        chip = ""
    elif c["model_unit"] == "pp":
        chip = f"Δ {chg:+.2f}pp model input"
    else:
        chip = f"Δ {chg:+.2%} MoM model input"
    detail = chip if c["kind"] == "rate" else f"index {c['level']:.1f} · base {c['base_year']} · {chip}"
    warn = " ⚠" if outsized else ""
    rel = c.get("release_date") or "n/a"
    return (f'<div class="mp-kpi" title="Released {rel}"><div class="lab">{c["label"]}</div>'
            f'<div class="val" style="color:{color};">{headline}{warn}</div>'
            f'<div class="kint" style="color:{color};">{interp}</div>'
            f'<div class="cap">{c["period_label"]} release</div>'
            f'<div class="cap" style="color:#7d93ab;font-size:11px;">{detail}</div></div>')


def _signal_counts(engine, alpha):
    obs = nsig = None
    b = getattr(engine, "betas", None)
    if b is not None and not b.empty:
        bd = b[b["freq"] == "daily"]
        if not bd.empty:
            if "n" in bd.columns:
                n = pd.to_numeric(bd["n"], errors="coerce")
                obs = int(n.max()) if n.notna().any() else None
            nsig = int(((bd["pvalue"] <= alpha) & (bd["asset"].isin(SECTOR_LABELS))).sum())
    return obs, nsig


def signal_quality(payload, obs, nsig, fresh, vdf=None):
    mc = payload.get("macro_cards", [])
    rel = (max(mc, key=lambda c: c.get("period", ""))["period_label"] if mc else None)
    items = [f"{rel} release incorporated" if rel else "Latest macro release incorporated"]
    if obs:
        items.append(f"{obs} daily observations analyzed")
    if nsig is not None:
        items.append(f"{nsig} statistically significant relationships detected")
    if vdf is not None and not vdf.empty:
        shipped = vdf[vdf["prod_significant"].astype(bool)]
        if not shipped.empty:
            nval = int((shipped["verdict"] == "validated").sum())
            npart = int((shipped["verdict"] == "partial").sum())
            items.append(f"{nval} of {len(shipped)} signals validated out-of-sample ({npart} partial)")
    items.append(f"Confidence: {(payload.get('confidence') or '—').capitalize()}")
    items.append(f"Data freshness: {'Current' if fresh else 'Unavailable'}")
    return items


def business_insight(ups, downs, ms):
    iip, cpi = ms.get("IIP_chg", 0.0), ms.get("CPI_chg", 0.0)
    up_secs = [u["sector"] for u in ups]
    down_secs = [d["sector"] for d in downs]
    lines = []
    if iip < 0:
        lines.append("Current conditions favour defensive consumption over cyclical manufacturing.")
    elif iip > 0:
        lines.append("Current conditions favour cyclical and industrial exposure over pure defensives.")
    if down_secs:
        nm = " and ".join(down_secs[:2])
        lines.append(f"If industrial weakness persists, earnings pressure may emerge first in {nm.lower()} "
                     f"and other rate- and demand-sensitive cyclicals.")
    if "IT" in up_secs:
        lines.append("Export-oriented technology businesses remain relatively insulated from domestic demand weakness.")
    elif cpi > 0:
        lines.append("With inflation elevated, pricing power and margin resilience become the key differentiators "
                     "across consumer names.")
    if not lines:
        lines = ["No decisive cross-sector skew under the current regime; positioning stays balanced "
                 "until the macro backdrop turns."]
    return lines


RIBBON_VERB = {
    "USDINR": ("the rupee weakened {v:.2f}%", "the rupee firmed {v:.2f}%"),
    "Nifty50": ("the Nifty rose {v:.2f}%", "the Nifty fell {v:.2f}%"),
    "BankNifty": ("Bank Nifty rose {v:.2f}%", "Bank Nifty fell {v:.2f}%"),
    "Gold": ("gold gained {v:.2f}%", "gold eased {v:.2f}%"),
    "BrentCrude": ("Brent firmed {v:.2f}%", "Brent softened {v:.2f}%"),
    "IndiaVIX": ("India VIX jumped {v:.2f}%", "India VIX eased {v:.2f}%"),
    "DXY": ("the dollar index rose {v:.2f}%", "the dollar index slipped {v:.2f}%"),
    "US10Y": ("US 10Y yields rose {v:.2f}%", "US 10Y yields fell {v:.2f}%"),
}


def _mover_phrase(m):
    up, down = RIBBON_VERB.get(m["indicator"], ("{l} rose {v:.2f}%", "{l} fell {v:.2f}%"))
    return (up if m["pct"] >= 0 else down).format(v=abs(m["pct"]), l=m.get("label", ""))


def _join_phrases(p):
    if not p:
        return ""
    s = p[0] if len(p) == 1 else ", ".join(p[:-1]) + " and " + p[-1]
    return s[0].upper() + s[1:]


def _risk_tone(rib):
    score = 0.0
    for m in rib:
        p, ind = m.get("pct"), m["indicator"]
        if p is None:
            continue
        if ind == "IndiaVIX":
            score += 1 if p > 0 else -1
        elif ind in ("Nifty50", "BankNifty"):
            score += 1 if p < 0 else -1
        elif ind == "USDINR":
            score += 1 if p > 0 else -1
        elif ind == "Gold":
            score += 0.5 if p > 0 else -0.5
    if score >= 1.5:
        return "a risk-off tone"
    if score <= -1.5:
        return "a risk-on tone"
    return "a mixed tape"


def morning_brief(payload, ms, ups, downs, obs, nsig):
    """Daily-led analyst note: market lede → regime backdrop → the model's read →
    daily-tone tilt → watch item → confidence-with-reason. Grounded in live numbers."""
    rib = payload.get("market_ribbon", [])
    cards = {c["indicator"]: c for c in payload.get("macro_cards", [])}
    movers = sorted([m for m in rib if m.get("pct") is not None], key=lambda m: -abs(m["pct"]))[:3]
    tone = _risk_tone(rib)
    lines = []

    if movers:
        lines.append(("lede", f"{_join_phrases([_mover_phrase(m) for m in movers])} — {tone} into today's session."))
    else:
        lines.append(("lede", "Markets are quiet across the daily complex into today's session."))

    reg = (payload.get("regime_badge") or payload.get("regime") or "mixed").lower()
    bits, ic, cc = [], cards.get("IIP"), cards.get("CPI")
    if ic and ic.get("model_chg") is not None:
        bits.append(f"industrial output {'contracted' if ic['model_chg'] < 0 else 'expanded'} "
                    f"{abs(ic['model_chg']):.0%} MoM")
    if cc and cc.get("yoy") is not None:
        band = ("above the RBI's 6% ceiling" if cc["yoy"] > 0.06
                else "in the upper half of the RBI band" if cc["yoy"] >= 0.04 else "within the RBI band")
        bits.append(f"CPI runs at {cc['yoy']:+.1%} YoY, {band}")
    backdrop = f"This lands against a {reg} backdrop"
    lines.append(("body", backdrop + ((" — " + " and ".join(bits) + ".") if bits else ".")))

    if ups or downs:
        parts = []
        if ups:
            a, _, c = sector_story(ups[0], ms)
            parts.append(f"flags {ups[0]['sector']} as the highest-conviction beneficiary "
                         f"({a.lower()}, {c.lower()} confidence)")
        if downs:
            parts.append(f"reads {downs[0]['sector']} as the most exposed sector")
        lines.append(("body", "MacroPulse's sensitivity model " + " and ".join(parts) + "."))

    if "risk-off" in tone and ups:
        lines.append(("body", f"Today's defensive tape reinforces that tilt toward {ups[0]['sector']} "
                              f"and away from cyclicals."))
    elif "risk-on" in tone and downs:
        lines.append(("body", f"Today's risk appetite may cushion cyclicals like {downs[0]['sector']} near "
                              f"term, even as the slower macro signal argues the other way."))

    outs = payload.get("outsized_factors", [])
    if outs:
        o = outs[0]
        lines.append(("watch", f"Watch: {FACTOR_LABEL.get(o['factor'], o['factor']).lower()} is an outsized "
                              f"input ({o['z']:+.1f}σ) — confirm in the next release before sizing conviction."))
    else:
        lines.append(("watch", "Watch: a sustained rupee break or a VIX spike would pressure rate-sensitive "
                              "cyclicals first."))

    conf = (payload.get("confidence") or "—").capitalize()
    cl = f"Confidence: {conf}"
    if nsig is not None and obs:
        cl += f" · {nsig} significant relationships across {obs} daily observations"
    if outs:
        cl += "; tempered by the outsized macro input"
    lines.append(("conf", cl + "."))
    return lines


def _fig_base(fig, n):
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      height=max(200, 54 * n), margin=dict(l=8, r=48, t=14, b=10), font_color="#DCE7F3",
                      yaxis_title=None, xaxis=dict(zeroline=True, zerolinecolor="rgba(255,255,255,.22)",
                                                   gridcolor="rgba(255,255,255,.05)"))
    return fig


def sector_pressure_fig(active):
    """Diverging horizontal bars — implied daily return per sector, green up / red down."""
    if not active:
        return None
    a = sorted(active, key=lambda s: s["implied_pct"])
    vals = [s["implied_pct"] for s in a]
    fig = go.Figure(go.Bar(x=vals, y=[s["sector"] for s in a], orientation="h",
                           marker_color=[GOOD if v >= 0 else BAD for v in vals],
                           text=[f"{v:+.2f}%" for v in vals], textposition="outside", cliponaxis=False))
    _fig_base(fig, len(a)).update_layout(xaxis_title="implied daily return (%)")
    return fig


def driver_decomp_fig(active):
    """Stacked diverging bars — each macro factor's contribution to a sector's implied move."""
    if not active:
        return None
    secs = [s["sector"] for s in active]
    fig = go.Figure()
    for f in ("CPI_chg", "IIP_chg", "Unemployment_chg"):
        xs = [next((d["contribution_pct"] for d in s.get("drivers", []) if d["factor"] == f), 0.0) for s in active]
        if any(abs(x) > 1e-9 for x in xs):
            fig.add_bar(name=FACTOR_LABEL.get(f, f), y=secs, x=xs, orientation="h", marker_color=FACTOR_COLOR.get(f))
    _fig_base(fig, len(secs)).update_layout(barmode="relative", xaxis_title="contribution to implied move (%)",
                                            legend=dict(orientation="h", y=1.18, x=0, font=dict(size=11, color="#DCE7F3")))
    return fig


# ---- advanced settings (collapsed sidebar) ----------------------------------
with st.sidebar:
    st.markdown("### ⚙ Advanced settings")
    st.caption("Validation controls — not needed for the default decision view.")
    alpha = st.slider("Significance α", 0.01, 0.20, 0.10, 0.01)
    freq = st.radio("Frequency (research & sim)", ["daily", "monthly"], horizontal=True)
    sig_only = st.checkbox("Significant betas only", value=True)
    use_llm = st.checkbox("AI narration (needs API key)", value=False)
    if st.button("↻ Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

st.markdown(CSS, unsafe_allow_html=True)
engine = get_engine()
payload = get_payload(alpha, "daily", None)
if not (payload.get("macro_state") and str(payload.get("asof")) not in ("None", "")):
    get_payload.clear()
    payload = get_payload(alpha, "daily", None)

ms = payload.get("macro_state", {})
asof = payload.get("asof")
fresh = bool(ms) and str(asof) not in ("None", "")
cpi, iip, ur = ms.get("CPI_chg", 0.0), ms.get("IIP_chg", 0.0), ms.get("Unemployment_chg", 0.0)
out_factors = {o["factor"] for o in payload.get("outsized_factors", [])}
ups = [s for s in payload.get("active_sectors", []) if s["direction"] == "up"]
downs = [s for s in payload.get("active_sectors", []) if s["direction"] == "down"]
conf = (payload.get("confidence") or "—").capitalize()
obs, nsig = _signal_counts(engine, alpha)
vdf = get_validation()
vlook = val_lookup(vdf)

# ---- market ribbon ----------------------------------------------------------
ribbon = payload.get("market_ribbon", [])
if ribbon:
    ai_header('<span class="mp-sub" style="margin:0;">Daily market pulse</span>', "market_pulse")
    cells = ""
    for m in ribbon:
        pc = m.get("pct")
        col = GOOD if (pc or 0) >= 0 else BAD
        val = "" if m["value"] is None else f"{m['value']:,.2f}"
        pct = "" if pc is None else f' <span style="color:{col};">{pc:+.2f}%</span>'
        cells += f'<span class="mp-tick"><b>{m["label"]}</b>{val}{pct}</span>'
    cells += f'<span class="mp-tick mp-asof">● live · {payload.get("market_asof")}</span>'
    st.markdown(f'<div class="mp-ribbon">{cells}</div>', unsafe_allow_html=True)

# ---- hero -------------------------------------------------------------------
fresh_chip = (f'<span class="mp-chip" style="color:{GOOD};">● data live</span>' if fresh
              else f'<span class="mp-chip" style="color:{BAD};">● no data</span>')
st.markdown(
    f'<div class="mp-hero mp-glass"><div>'
    f'<div class="mp-eyebrow">India · macro decision intelligence</div>'
    f'<div class="mp-name"><span class="mp-flag">IN</span>MacroPulse India</div>'
    f'<div class="mp-sub">Today\'s macro regime</div>'
    f'{regime_pills(ms)}</div>'
    f'<div class="mp-meta"><span class="mp-chip">🕒 updated {asof}</span><br>{fresh_chip}<br>'
    f'<span class="mp-chip">confidence: {conf}</span></div></div>',
    unsafe_allow_html=True)
ai_header('<span class="mp-sub" style="margin:0;">What does today\'s regime mean?</span>',
          "regime", body=regime_explanation(ms), ratio=(0.7, 0.3))

if not fresh:
    st.error("Macro state is empty for this connection — `analysis_daily` returned no rows, so every "
             "sector reads as 'no exposure'. This is a data/connection issue, not a real 'no signal'. "
             "Run `python rebuild_analytics.py` on this DB or check `DB_NAME`/`DB_HOST`, then Refresh.")

# ---- macro evidence (so-what KPIs) ------------------------------------------
cards = {c["indicator"]: c for c in payload.get("macro_cards", [])}
if cards:
    ai_header('<span class="mp-sub" style="margin:0;">Macro indicators</span>', "kpi")
    cols = st.columns(3)
    for col, ind in zip(cols, ["CPI", "IIP", "Unemployment"]):
        if cards.get(ind):
            col.markdown(macro_kpi(cards[ind], outsized=CHG_OF[ind] in out_factors), unsafe_allow_html=True)

# ---- MORNING BRIEF (daily analyst note) -------------------------------------
brief_lines = morning_brief(payload, ms, ups, downs, obs, nsig)
parts = ""
for typ, txt in brief_lines:
    if typ == "lede":
        parts += f'<div class="ln">{txt}</div>'
    elif typ == "body":
        parts += f'<div class="lnb">{txt}</div>'
    elif typ == "watch":
        parts += f'<div class="lnw">👁 {txt}</div>'
    else:
        parts += f'<div class="conf">{txt}</div>'
ai_header('<span class="mp-sub" style="margin:0;color:#00F5D4;">Morning brief · daily note</span>',
          "morning_brief")
st.markdown(f'<div class="mp-brief mp-glass">{parts}</div>', unsafe_allow_html=True)
with st.expander("Sector pressure detail · visual"):
    figA = sector_pressure_fig(payload.get("active_sectors", []))
    if figA:
        st.markdown("<div style='color:#9fb3c8;font-size:13px;margin-bottom:2px;'>Implied daily return by sector "
                    "— green benefits, red under pressure.</div>", unsafe_allow_html=True)
        st.plotly_chart(figA, use_container_width=True, config={"displayModeBar": False})
    else:
        st.caption("No significant sector pressure under the current macro state.")
    if use_llm:
        t = render_llm(payload)
        if t:
            st.markdown(t)

# ---- signal quality (trust panel) -------------------------------------------
sq = signal_quality(payload, obs, nsig, fresh, vdf)
ai_header('<span class="mp-sub" style="margin:0;">Signal quality</span>', "signal_quality")
sq_html = "".join(f'<span class="it"><span class="ck">✓</span>{x}</span>' for x in sq)
st.markdown(f'<div class="mp-sq mp-glass">{sq_html}</div>', unsafe_allow_html=True)

# ---- winners & losers -------------------------------------------------------
st.markdown('<div class="sec-h">Beneficiaries &nbsp;·&nbsp; Under pressure</div>', unsafe_allow_html=True)
w, l = st.columns(2)
with w:
    ai_header(f'<span style="color:{GOOD};font-weight:700;">🟢 Beneficiaries</span>',
              "beneficiaries", ratio=(0.55, 0.45))
    if ups:
        for s in ups:
            st.markdown(wl_card(s, True, ms, validation_chip(verdict_for(s, vlook))), unsafe_allow_html=True)
    else:
        st.markdown('<div class="mp-wl mp-wl-story">No sector flagged as a clear beneficiary right now.</div>', unsafe_allow_html=True)
with l:
    ai_header(f'<span style="color:{BAD};font-weight:700;">🔴 Under pressure</span>',
              "under_pressure", ratio=(0.55, 0.45))
    if downs:
        for s in downs:
            st.markdown(wl_card(s, False, ms, validation_chip(verdict_for(s, vlook))), unsafe_allow_html=True)
    else:
        st.markdown('<div class="mp-wl mp-wl-story">No sector flagged as clearly vulnerable right now.</div>', unsafe_allow_html=True)
    ne = payload.get("no_exposure_sectors", [])
    if ne:
        st.markdown(f'<div class="mp-wl" style="border-style:dashed;border-color:rgba(255,255,255,.1);">'
                    f'<div class="mp-wl-h"><span class="mp-wl-name" style="font-size:16px;color:#9fb3c8;">'
                    f'<span class="dot" style="background:#5f7488;margin-right:10px;"></span>Neutral</span></div>'
                    f'<div class="mp-wl-arch">No significant exposure</div>'
                    f'<div class="mp-wl-story">{", ".join(ne)} show no statistically significant link to the '
                    f'current factors — neither tailwind nor headwind this cycle.</div></div>', unsafe_allow_html=True)

# ---- scenario intelligence (compact, secondary) -----------------------------
ai_header('<span class="sec-h" style="margin:0;">Scenario intelligence</span>', "scenario")
if "scenario" not in st.session_state:
    st.session_state.scenario = "Stagflation"
scols = st.columns(4)
for col, (disp, key, emoji, tag) in zip(scols, SCENARIO_CARDS):
    if col.button(f"{emoji} {disp}", key=f"sc_{key}", use_container_width=True):
        st.session_state.scenario = disp
disp = st.session_state.scenario
sim = WhatIfSimulator(engine=engine)
res = sim.simulate(SCENARIOS[SCENARIO_KEY[disp]], freq="daily", alpha=alpha, significant_only=sig_only)
ben_html = vul_html = '<span class="mp-asof">None flagged.</span>'
if not res.empty:
    lab = "sector" if "sector" in res.columns else "asset"
    rr = res.copy()
    if lab == "asset":
        rr["sector"] = rr["asset"].map(SECTOR_LABELS).fillna(rr["asset"])
    ben = list(rr[rr["response"] > 0].sort_values("response", ascending=False)["sector"])
    vul = list(rr[rr["response"] < 0].sort_values("response")["sector"])
    if ben:
        ben_html = "".join(f'<span class="mp-pill">🟢 {s}</span>' for s in ben)
    if vul:
        vul_html = "".join(f'<span class="mp-pill">🔴 {s}</span>' for s in vul)
st.markdown(
    f'<div class="mp-glass" style="padding:15px 20px;">'
    f'<div style="font-size:15px;font-weight:700;color:#fff;margin-bottom:9px;">{disp}</div>'
    f'<div style="font-size:12px;color:{GOOD};margin-bottom:4px;">Likely beneficiaries</div>{ben_html}'
    f'<div style="font-size:12px;color:{BAD};margin:9px 0 4px;">Likely vulnerable</div>{vul_html}'
    f'<div style="font-size:13.5px;line-height:1.55;color:#bccadb;margin-top:11px;'
    f'border-top:1px solid rgba(255,255,255,.07);padding-top:10px;">{SCENARIO_INTERP.get(disp,"")}</div></div>',
    unsafe_allow_html=True)
with st.expander("Advanced scenario tools · custom macro shock builder"):
    st.markdown(
        "<span style='color:#B7C7D9;font-size:15px;'>Build a custom macro regime. Define inflation, "
        "industrial activity and labour-market assumptions to project likely sector beneficiaries "
        "and vulnerabilities.</span>", unsafe_allow_html=True)
    cpi_opts = {"holds steady": 0.0, "rises 0.5%": 0.005, "rises 1%": 0.01, "rises 2%": 0.02,
                "falls 0.5%": -0.005, "falls 1%": -0.01}
    iip_opts = {"holds steady": 0.0, "rises 3%": 0.03, "rises 6%": 0.06,
                "falls 3%": -0.03, "falls 6%": -0.06, "falls 9%": -0.09}
    ur_opts = {"holds steady": 0.0, "rises 0.5pp": 0.5, "rises 1pp": 1.0,
               "falls 0.5pp": -0.5, "falls 1pp": -1.0}
    q1, q2, q3 = st.columns(3)
    cpi_c = q1.selectbox("If inflation…", list(cpi_opts), key="cu_cpi")
    iip_c = q2.selectbox("…and industrial output…", list(iip_opts), key="cu_iip")
    ur_c = q3.selectbox("…and unemployment…", list(ur_opts), key="cu_ur")
    cu = {}
    if cpi_opts[cpi_c]:
        cu["CPI_chg"] = cpi_opts[cpi_c]
    if iip_opts[iip_c]:
        cu["IIP_chg"] = iip_opts[iip_c]
    if ur_opts[ur_c]:
        cu["Unemployment_chg"] = ur_opts[ur_c]
    st.markdown(f'<div style="font-size:14.5px;color:#cfe0f2;margin:8px 0 2px;">Scenario · inflation '
                f'<b>{cpi_c}</b>, industrial output <b>{iip_c}</b>, unemployment <b>{ur_c}</b>.</div>',
                unsafe_allow_html=True)
    if not cu:
        st.markdown(
            "<div style='color:#B7C7D9;font-size:14px;'>"
            "Select one or more macro changes to estimate sector impacts.</div>",
            unsafe_allow_html=True)
    else:
        cr = sim.simulate(cu, freq="daily", alpha=alpha, significant_only=sig_only)
        if cr.empty:
            st.caption("No sectors clear the significance threshold under this scenario.")
        else:
            clab = "sector" if "sector" in cr.columns else "asset"
            cc = cr.copy()
            if clab == "asset":
                cc["sector"] = cc["asset"].map(SECTOR_LABELS).fillna(cc["asset"])
            cben = list(cc[cc["response"] > 0].sort_values("response", ascending=False)["sector"])
            cvul = list(cc[cc["response"] < 0].sort_values("response")["sector"])
            bh = "".join(f'<span class="mp-pill">🟢 {s}</span>' for s in cben) or '<span class="mp-asof">None.</span>'
            vh = "".join(f'<span class="mp-pill">🔴 {s}</span>' for s in cvul) or '<span class="mp-asof">None.</span>'
            st.markdown(f'<div style="font-size:12px;color:{GOOD};margin-top:8px;">Likely beneficiaries</div>{bh}'
                        f'<div style="font-size:12px;color:{BAD};margin:9px 0 4px;">Likely vulnerable</div>{vh}',
                        unsafe_allow_html=True)

# ---- business interpretation ------------------------------------------------
ai_header('<span class="sec-h" style="margin:0;">Business interpretation</span>', "business_interpretation")
bullets = "".join(f'<li style="margin-bottom:9px;">{x}</li>' for x in business_insight(ups, downs, ms))
st.markdown(f'<div class="mp-glass" style="padding:20px 26px;">'
            f'<ul style="font-size:15.5px;line-height:1.55;color:#dce7f3;margin:0;padding-left:20px;">{bullets}</ul></div>',
            unsafe_allow_html=True)
figB = driver_decomp_fig(payload.get("active_sectors", []))
if figB:
    st.markdown("<div style='color:#9fb3c8;font-size:13px;margin:14px 0 2px;'>What's driving each call — "
                "contribution of each macro factor to the implied move. This chart updates as the data changes.</div>",
                unsafe_allow_html=True)
    st.plotly_chart(figB, use_container_width=True, config={"displayModeBar": False})

# ---- methodology & validation (background) ----------------------------------
ai_header('<span class="sec-h" style="margin:0;">Methodology &amp; validation</span>', "methodology")
with st.expander("Open the audit layer"):
    st.markdown(
        "<div style='color:#B7C7D9;font-size:14px;'>"
        "Audit layer — regression betas, significance, R², correlations. For validation only.</div>",
        unsafe_allow_html=True)
    sct = st.selectbox("Sector → factor sensitivities", list(SECTOR_LABELS.values()), key="rs_sector")
    st.dataframe(engine.sector_view(INV_LABELS[sct], freq=freq), hide_index=True, use_container_width=True)
    fac = st.selectbox("Factor → all sectors", FACTORS, key="rs_factor")
    fv = engine.factor_view(fac, freq=freq)
    fv = fv[fv["asset"].isin(SECTOR_LABELS)].copy()
    if not fv.empty:
        fv.insert(0, "sector", fv["asset"].map(SECTOR_LABELS))
        st.dataframe(fv[["sector", "beta", "pvalue", "r2", "n"]], hide_index=True, use_container_width=True)
    sig = payload.get("significant_sensitivities", [])
    if sig:
        st.markdown(
            "<span style='color:#DCE7F3;font-size:20px;font-weight:600;'>"
            "Significant sensitivities</span>", unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(sig), hide_index=True, use_container_width=True)
    cm = engine.correlation_matrix(freq=freq)
    if not cm.empty:
        cm = cm[cm.index.isin(SECTOR_LABELS)].rename(index=SECTOR_LABELS)
        st.markdown(
            "<span style='color:#DCE7F3;font-size:20px;font-weight:600;'>"
            "Correlation matrix (sectors)</span>", unsafe_allow_html=True)
        st.dataframe(cm, use_container_width=True)
    if not vdf.empty:
        st.markdown(
            "<span style='color:#DCE7F3;font-size:20px;font-weight:600;'>"
            "Out-of-sample validation (monthly, point-in-time)</span>", unsafe_allow_html=True)
        st.markdown(
            "<div style='color:#B7C7D9;font-size:13px;margin-bottom:6px;'>Walk-forward verdict per signal. "
            "<b>wf_r2</b> &gt; 0 beats a naive mean; <b>wf_hit</b> is directional accuracy. "
            "n ≈ 13 months — an early robustness read, not proof.</div>", unsafe_allow_html=True)
        vshow = vdf.copy()
        vshow["sector"] = vshow["asset"].map(lambda a: SECTOR_LABELS.get(a)
                                             or SECTOR_LABELS.get(_strip_suffix(a)) or _strip_suffix(a))
        vshow = vshow.sort_values(["prod_significant", "verdict"], ascending=[False, True])
        st.dataframe(vshow[["sector", "factor", "prod_significant", "verdict",
                            "wf_r2", "wf_hit", "holdout_r2", "sign_stable", "n_wf"]],
                     hide_index=True, use_container_width=True)