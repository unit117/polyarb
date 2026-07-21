"""Second-opinion code audit for PolyArb (defaults to Kimi / Moonshot).

Reads core source files, sends them to a reasoning model via an OpenAI-compatible
API, and asks for a bug/logic review. Outputs a timestamped markdown report.

Provider is configurable and defaults to Kimi (Moonshot). The legacy DEEPSEEK_*
env names are honored as a fallback so existing setups keep working:
  - AUDIT_API_KEY            (fallback: DEEPSEEK_API_KEY, then CLASSIFIER_API_KEY)
  - AUDIT_BASE_URL           (fallback: DEEPSEEK_BASE_URL; default https://api.moonshot.ai/v1)
  - AUDIT_MODEL              (fallback: DEEPSEEK_MODEL; default kimi-k2.6)
  - AUDIT_REASONING_EFFORT   (fallback: DEEPSEEK_REASONING_EFFORT; DeepSeek-only)

Usage:
    python -m scripts.deepseek_audit
"""

import os
import sys
import datetime
from pathlib import Path

from openai import OpenAI


def _load_env_value(key_name: str, default: str = "") -> str:
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
    return default


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = PROJECT_ROOT / "reports"
REPORT_DIR.mkdir(exist_ok=True)

# Audit provider config. Defaults to Kimi (Moonshot); the legacy DEEPSEEK_* names
# are honored as a fallback so existing setups keep working.
AUDIT_BASE_URL = (
    _load_env_value("AUDIT_BASE_URL")
    or _load_env_value("DEEPSEEK_BASE_URL")
    or "https://api.moonshot.ai/v1"
)
AUDIT_MODEL = (
    _load_env_value("AUDIT_MODEL")
    or _load_env_value("DEEPSEEK_MODEL")
    or "kimi-k2.6"
)
AUDIT_REASONING_EFFORT = (
    _load_env_value("AUDIT_REASONING_EFFORT")
    or _load_env_value("DEEPSEEK_REASONING_EFFORT")
    or "high"
)
# reasoning_effort is a DeepSeek-specific extension; Moonshot rejects unknown
# params, so it's only sent when the endpoint is DeepSeek.
_IS_DEEPSEEK = "deepseek" in AUDIT_BASE_URL.lower()

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
    """Load an API key from env or .env."""
    return _load_env_value(key_name)


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


def call_audit_model(user_prompt: str) -> str:
    """Call the audit model via its OpenAI-compatible API (Kimi by default)."""
    api_key = (
        _load_env_value("AUDIT_API_KEY")
        or _load_env_value("DEEPSEEK_API_KEY")
        or _load_env_value("CLASSIFIER_API_KEY")
    )
    if not api_key:
        raise RuntimeError(
            "No audit API key found "
            "(set AUDIT_API_KEY, DEEPSEEK_API_KEY, or CLASSIFIER_API_KEY)"
        )

    client = OpenAI(api_key=api_key, base_url=AUDIT_BASE_URL)

    print(
        f"Sending {len(user_prompt):,} chars to {AUDIT_MODEL} "
        f"via {AUDIT_BASE_URL}..."
    )

    kwargs = {
        "model": AUDIT_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        # Kimi k2.6 caps output below DeepSeek's 64k; stay safe on Moonshot.
        "max_tokens": 65536 if _IS_DEEPSEEK else 32768,
        # Enable reasoning for a deep audit. Both DeepSeek V4 and Kimi k2.5/k2.6
        # accept this body; k2.6 also reasons by default.
        "extra_body": {"thinking": {"type": "enabled"}},
    }
    if _IS_DEEPSEEK:
        kwargs["reasoning_effort"] = AUDIT_REASONING_EFFORT

    response = client.chat.completions.create(**kwargs)
    if response.choices and response.choices[0].finish_reason:
        print(f"  Finish reason: {response.choices[0].finish_reason}")
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError(f"{AUDIT_MODEL} returned an empty response")
    return content


def main():
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    date_slug = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d-%H%M")

    print(f"PolyArb Code Audit ({AUDIT_MODEL}) — {timestamp}")
    print(f"Loading {len(AUDIT_FILES)} source files...")

    file_contents = load_files()
    report_context = load_latest_report()

    user_prompt = USER_PROMPT_TEMPLATE.format(
        timestamp=timestamp,
        file_contents=file_contents + report_context,
    )

    try:
        response = call_audit_model(user_prompt)
    except Exception as e:
        print(f"ERROR: audit API failed: {e}", file=sys.stderr)
        sys.exit(1)

    # Write report
    report_path = REPORT_DIR / f"audit-{date_slug}.md"
    report = f"# PolyArb Code Audit — {timestamp}\n\n"
    report += f"*Model: {AUDIT_MODEL} ({AUDIT_BASE_URL})*\n"
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
