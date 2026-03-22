"""Gemini second-opinion audit for PolyArb.

Reads core source files, sends them to Gemini, and asks for a bug/logic
review. Outputs a timestamped markdown report.

Supports two backends:
  1. Google AI API (GEMINI_API_KEY) — free tier, preferred
  2. OpenRouter (OPENROUTER_API_KEY) — fallback

Usage:
    python -m scripts.gemini_audit
"""

import os
import sys
import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = PROJECT_ROOT / "reports"
REPORT_DIR.mkdir(exist_ok=True)

MODEL_GOOGLE = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
MODEL_OPENROUTER = "google/gemini-3-flash-preview"

# Files to include in the audit context — the critical execution path
AUDIT_FILES = [
    "services/simulator/portfolio.py",
    "services/simulator/pipeline.py",
    "services/optimizer/trades.py",
    "services/optimizer/frank_wolfe.py",
    "services/detector/classifier.py",
    "services/detector/verification.py",
    "services/detector/constraints.py",
    "services/ingestor/main.py",
    "services/simulator/main.py",
    "services/optimizer/main.py",
    "services/dashboard/web/src/components/StatsBar.tsx",
    "shared/config.py",
    "shared/models.py",
    "shared/events.py",
    "CLAUDE.md",
    "IMPROVEMENT_PLAN.md",
]

SYSTEM_PROMPT = """\
You are a senior quantitative developer auditing a prediction-market \
arbitrage system called PolyArb.

Your job: find bugs, logic errors, accounting mistakes, missed edge cases, \
and anything that would cause the system to lose money or report incorrect \
metrics. Be specific — cite file names, line numbers, and exact code paths.

Structure your response as:
## Critical (will lose money or corrupt state)
## High (likely causes incorrect behavior in production)
## Medium (suboptimal, could mask problems)
## Suggestions (improvements, not bugs)

For each finding, include:
- **What**: one-line description
- **Where**: file + line range
- **Why**: explain the failure mode
- **Fix**: concrete code change suggestion

IMPORTANT:
- Do NOT repeat issues already documented in IMPROVEMENT_PLAN.md
- Do NOT suggest adding tests or generic best practices
- Do NOT suggest architectural rewrites
- Focus only on NEW bugs and risks not already known
- If you find nothing new, say "None found." honestly

Be ruthless. Do not pad with compliments.
"""

USER_PROMPT_TEMPLATE = """\
Below are the core source files for PolyArb, a combinatorial arbitrage \
detection and paper-trading system for Polymarket prediction markets.

The system uses Frank-Wolfe optimization to find arbitrage across correlated \
binary markets. It detects market pairs via pgvector embeddings, classifies \
their logical dependency (implication, partition, mutual_exclusion, \
conditional), builds constraint matrices, optimizes trade allocations, and \
paper-trades them with VWAP execution simulation.

Current live status (as of {timestamp}):
- ~37k active markets, ~4.6k pairs, ~3.9k paper trades
- Starting capital: $10,000
- Live trading is disabled; this is paper-only

Please audit these files for bugs, logic errors, and accounting issues. \
Focus on things NOT already in IMPROVEMENT_PLAN.md:

{file_contents}
"""


def _load_env_key(key_name: str) -> str:
    """Try env var first, then parse from .env file."""
    val = os.environ.get(key_name, "")
    if val:
        return val
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{key_name}="):
                return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def load_files() -> str:
    """Read audit files and format them for the prompt."""
    sections = []
    for relpath in AUDIT_FILES:
        fpath = PROJECT_ROOT / relpath
        if not fpath.exists():
            sections.append(f"### {relpath}\n[FILE NOT FOUND]\n")
            continue
        content = fpath.read_text(errors="replace")
        lines = content.splitlines()
        if len(lines) > 500:
            content = "\n".join(lines[:500]) + f"\n\n... [truncated, {len(lines)} total lines]"
        sections.append(f"### {relpath}\n```\n{content}\n```\n")
    return "\n".join(sections)


def load_latest_report() -> str:
    """Load the most recent daily report if available."""
    reports = sorted(REPORT_DIR.glob("daily-report-*.md"), reverse=True)
    if not reports:
        reports = sorted(REPORT_DIR.glob("report-*.md"), reverse=True)
    if not reports:
        return ""
    content = reports[0].read_text(errors="replace")
    return f"\n### Latest Daily Report: {reports[0].name}\n```\n{content}\n```\n"


def call_gemini_google(user_prompt: str) -> str:
    """Call Gemini via Google AI API (free tier)."""
    import warnings
    warnings.filterwarnings("ignore", category=FutureWarning)
    import google.generativeai as genai

    api_key = _load_env_key("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not found")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        MODEL_GOOGLE,
        system_instruction=SYSTEM_PROMPT,
    )

    print(f"Sending {len(user_prompt):,} chars to {MODEL_GOOGLE} via Google AI API...")

    response = model.generate_content(
        user_prompt,
        generation_config=genai.GenerationConfig(
            max_output_tokens=65536,
            temperature=0.3,
        ),
    )

    # Check for truncation
    if response.candidates and response.candidates[0].finish_reason:
        reason = response.candidates[0].finish_reason
        print(f"  Finish reason: {reason}")

    return response.text


def call_gemini_openrouter(user_prompt: str) -> str:
    """Call Gemini via OpenRouter (fallback)."""
    from openai import OpenAI

    api_key = _load_env_key("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not found")

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    print(f"Sending {len(user_prompt):,} chars to {MODEL_OPENROUTER} via OpenRouter...")

    response = client.chat.completions.create(
        model=MODEL_OPENROUTER,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=65536,
        temperature=0.3,
    )
    return response.choices[0].message.content


def main():
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    date_slug = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d-%H%M")

    print(f"PolyArb Gemini Audit — {timestamp}")
    print(f"Loading {len(AUDIT_FILES)} source files...")

    file_contents = load_files()
    report_context = load_latest_report()

    user_prompt = USER_PROMPT_TEMPLATE.format(
        timestamp=timestamp,
        file_contents=file_contents + report_context,
    )

    # Try Google AI API first (free), fall back to OpenRouter
    backend = "unknown"
    try:
        response = call_gemini_google(user_prompt)
        backend = f"Google AI ({MODEL_GOOGLE})"
    except Exception as e:
        print(f"Google AI API failed ({e}), trying OpenRouter...")
        try:
            response = call_gemini_openrouter(user_prompt)
            backend = f"OpenRouter ({MODEL_OPENROUTER})"
        except Exception as e2:
            print(f"ERROR: Both backends failed.\n  Google: {e}\n  OpenRouter: {e2}", file=sys.stderr)
            sys.exit(1)

    # Write report
    report_path = REPORT_DIR / f"gemini-audit-{date_slug}.md"
    report = f"# PolyArb Gemini Audit — {timestamp}\n\n"
    report += f"*Model: {backend}*\n"
    report += f"*Files audited: {len(AUDIT_FILES)}*\n\n---\n\n"
    report += response

    report_path.write_text(report)
    print(f"\nReport saved to: {report_path}")
    print(f"\n{'='*60}")
    print(response[:3000])
    if len(response) > 3000:
        print(f"\n... [{len(response):,} total chars, see full report]")

    return str(report_path)


if __name__ == "__main__":
    main()
