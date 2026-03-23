"""Shared prompt specs and renderers for classifier LLM calls."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any, Mapping


@dataclass(frozen=True)
class PromptSpec:
    """Canonical prompt semantics for a classifier prompt family."""

    family: str
    version: str
    role: str
    objective: str
    why_this_matters: str = ""
    definitions: tuple[str, ...] = ()
    hard_rules_heading: str = ""
    hard_rules: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    output_schema: str = ""
    final_instruction: str = ""


@dataclass(frozen=True)
class RenderedPrompt:
    """Concrete prompt payload plus reusable/request-specific split."""

    family: str
    version: str
    adapter: str
    reusable_prefix: str
    request_suffix: str
    messages: tuple[dict[str, str], ...]


LABEL_PROMPT_SPEC_V1 = PromptSpec(
    family="label",
    version="label_v1",
    role="You classify the logical dependency between two prediction markets.",
    objective=(
        "Given two markets with their questions, descriptions, and outcomes, determine:\n"
        '1. dependency_type: one of "implication", "partition", "mutual_exclusion", '
        '"conditional", or "none"\n'
        "2. confidence: float 0-1\n"
        '3. correlation: "positive" or "negative" (REQUIRED when dependency_type is "conditional")'
    ),
    definitions=(
        "implication: If market A resolves Yes, market B must resolve a specific way (or vice versa)",
        "partition: Markets A and B together form an exhaustive partition of the same event space",
        "mutual_exclusion: Markets A and B cannot both resolve Yes simultaneously",
        "conditional: Market A's outcome probabilities are logically constrained by market B's outcome",
        'positive correlation: A=Yes makes B=Yes more likely (e.g., "Win Iowa" -> "Win Election")',
        'negative correlation: A=Yes makes B=Yes less likely (e.g., "Team A wins" -> "Team B wins")',
    ),
    hard_rules_heading="CRITICAL — price-threshold markets:",
    hard_rules=(
        '"X above $A" and "X above $B" where A > B: this is IMPLICATION, not mutual_exclusion.\n'
        'If X is above $134, it is necessarily also above $128. Both CAN resolve Yes simultaneously.',
        '"X above $A" and "X above $B" on DIFFERENT dates or time windows: these are INDEPENDENT (none).\n'
        "The price can be above $128 on Monday and below $128 on Tuesday.",
        'Only use mutual_exclusion when the events truly cannot BOTH happen (e.g., "Team A wins" vs '
        '"Team B wins" in the same game).',
    ),
    output_schema=(
        '{"dependency_type": "...", "confidence": 0.XX, "correlation": "positive"|"negative"|null, '
        '"reasoning": "..."}'
    ),
    final_instruction="Respond ONLY with valid JSON:",
)

RESOLUTION_VECTOR_PROMPT_SPEC_V1 = PromptSpec(
    family="resolution_vector",
    version="resolution_v1",
    role="You are a prediction market analyst.",
    objective="Given two binary markets A and B, determine ALL logically valid outcome combinations.",
    hard_rules_heading="Rules:",
    hard_rules=(
        "Each market resolves to exactly one outcome.",
        "List every combination of (A_outcome, B_outcome) that is logically possible.",
        "Only exclude a combination if it is LOGICALLY IMPOSSIBLE — not merely unlikely.",
        "Correlation or probability does NOT make a combination invalid.",
        "IMPORTANT: If both markets ask whether different entities will achieve the SAME singular outcome "
        '(e.g., "Will X win the award?" and "Will Y win the award?", or "Will X lead the league in stat?" '
        'and "Will Y lead the league in stat?"), then both cannot be Yes simultaneously — only one '
        "entity can win/lead. Exclude (Yes, Yes) in that case.",
    ),
    output_schema=(
        '{"valid_outcomes": [{"a": "Yes", "b": "Yes"}, {"a": "Yes", "b": "No"}, ...], '
        '"reasoning": "<one sentence explaining the logical relationship>", '
        '"confidence": <float 0.0-1.0>}'
    ),
    final_instruction="Return strictly valid JSON with no additional text:",
)


def _join_blocks(*blocks: str) -> str:
    return "\n\n".join(block for block in blocks if block)


def _render_bullet_block(heading: str, items: tuple[str, ...]) -> str:
    lines = [heading] if heading else []
    lines.extend(f"- {item}" for item in items)
    return "\n".join(lines)


def _render_examples(spec: PromptSpec) -> str:
    if not spec.examples:
        return ""
    return _render_bullet_block("Examples:", spec.examples)


def _market_block(label: str, market: Mapping[str, Any]) -> str:
    return (
        f"{label}:\n"
        f"- Question: {market.get('question', '')}\n"
        f"- Description: {market.get('description', 'N/A')}\n"
        f"- Outcomes: {market.get('outcomes', [])}"
    )


def _resolution_market_line(label: str, market: Mapping[str, Any]) -> str:
    return f'{label}: "{market.get("question", "")}" — Outcomes: {market.get("outcomes", [])}'


def _render_generic_label_prefix(spec: PromptSpec) -> str:
    return _join_blocks(
        spec.role,
        spec.objective,
        f"Definitions:\n{_render_bullet_block('', spec.definitions)}" if spec.definitions else "",
        _render_bullet_block(spec.hard_rules_heading, spec.hard_rules),
        _render_examples(spec),
        f"{spec.final_instruction} {spec.output_schema}".strip(),
    )


def _render_generic_resolution_prefix(spec: PromptSpec) -> str:
    return _join_blocks(
        f"{spec.role} {spec.objective}".strip(),
        _render_bullet_block(spec.hard_rules_heading, spec.hard_rules),
        _render_examples(spec),
    )


def _render_label_suffix(market_a: Mapping[str, Any], market_b: Mapping[str, Any]) -> str:
    return _join_blocks(
        _market_block("Market A", market_a),
        _market_block("Market B", market_b),
    )


def _render_resolution_suffix(spec: PromptSpec, market_a: Mapping[str, Any], market_b: Mapping[str, Any]) -> str:
    return _join_blocks(
        "\n".join(
            (
                _resolution_market_line("Market A", market_a),
                _resolution_market_line("Market B", market_b),
            )
        ),
        f"{spec.final_instruction}\n{spec.output_schema}",
    )


def render_generic_prompt(
    spec: PromptSpec,
    market_a: Mapping[str, Any],
    market_b: Mapping[str, Any],
) -> RenderedPrompt:
    """Render a prompt for OpenAI-compatible chat completions APIs."""
    if spec.family == "label":
        reusable_prefix = _render_generic_label_prefix(spec)
        request_suffix = _render_label_suffix(market_a, market_b)
        messages = (
            {"role": "system", "content": reusable_prefix},
            {"role": "user", "content": request_suffix},
        )
        return RenderedPrompt(
            family=spec.family,
            version=spec.version,
            adapter="openai_generic",
            reusable_prefix=reusable_prefix,
            request_suffix=request_suffix,
            messages=messages,
        )

    if spec.family == "resolution_vector":
        reusable_prefix = _render_generic_resolution_prefix(spec)
        request_suffix = _render_resolution_suffix(spec, market_a, market_b)
        messages = (
            {"role": "user", "content": _join_blocks(reusable_prefix, request_suffix)},
        )
        return RenderedPrompt(
            family=spec.family,
            version=spec.version,
            adapter="openai_generic",
            reusable_prefix=reusable_prefix,
            request_suffix=request_suffix,
            messages=messages,
        )

    raise ValueError(f"Unsupported prompt family: {spec.family}")


def _render_claude_tag(tag: str, content: str) -> str:
    return f"<{tag}>{escape(content)}</{tag}>"


def _render_claude_label_suffix(market_a: Mapping[str, Any], market_b: Mapping[str, Any]) -> str:
    return _join_blocks(
        "<input>",
        _join_blocks(
            _join_blocks(
                "<market_a>",
                _render_claude_tag("question", str(market_a.get("question", ""))),
                _render_claude_tag("description", str(market_a.get("description", "N/A"))),
                _render_claude_tag("outcomes", str(market_a.get("outcomes", []))),
                "</market_a>",
            ),
            _join_blocks(
                "<market_b>",
                _render_claude_tag("question", str(market_b.get("question", ""))),
                _render_claude_tag("description", str(market_b.get("description", "N/A"))),
                _render_claude_tag("outcomes", str(market_b.get("outcomes", []))),
                "</market_b>",
            ),
        ),
        "</input>",
    )


def _render_claude_resolution_suffix(spec: PromptSpec, market_a: Mapping[str, Any], market_b: Mapping[str, Any]) -> str:
    return _join_blocks(
        "<input>",
        _join_blocks(
            _join_blocks(
                "<market_a>",
                _render_claude_tag("question", str(market_a.get("question", ""))),
                _render_claude_tag("outcomes", str(market_a.get("outcomes", []))),
                "</market_a>",
            ),
            _join_blocks(
                "<market_b>",
                _render_claude_tag("question", str(market_b.get("question", ""))),
                _render_claude_tag("outcomes", str(market_b.get("outcomes", []))),
                "</market_b>",
            ),
        ),
        "</input>",
        _join_blocks(
            "<output_schema>",
            escape(spec.output_schema),
            "</output_schema>",
            "<final_instruction>",
            escape(spec.final_instruction),
            "</final_instruction>",
        ),
    )


def render_claude_prompt(
    spec: PromptSpec,
    market_a: Mapping[str, Any],
    market_b: Mapping[str, Any],
) -> RenderedPrompt:
    """Render the canonical prompt spec in an XML-ish Claude-friendly layout."""
    reusable_prefix = _join_blocks(
        _render_claude_tag("role", spec.role),
        _render_claude_tag("objective", spec.objective),
        _render_claude_tag("why_this_matters", spec.why_this_matters) if spec.why_this_matters else "",
        _join_blocks(
            "<definitions>",
            *(f"<item>{escape(item)}</item>" for item in spec.definitions),
            "</definitions>",
        ) if spec.definitions else "",
        _join_blocks(
            f"<hard_rules title=\"{escape(spec.hard_rules_heading)}\">",
            *(f"<item>{escape(item)}</item>" for item in spec.hard_rules),
            "</hard_rules>",
        ) if spec.hard_rules else "",
        _join_blocks(
            "<examples>",
            *(f"<item>{escape(item)}</item>" for item in spec.examples),
            "</examples>",
        ) if spec.examples else "",
    )

    if spec.family == "label":
        request_suffix = _join_blocks(
            _render_claude_label_suffix(market_a, market_b),
            _join_blocks(
                "<output_schema>",
                escape(spec.output_schema),
                "</output_schema>",
                "<final_instruction>",
                escape(spec.final_instruction),
                "</final_instruction>",
            ),
        )
    elif spec.family == "resolution_vector":
        request_suffix = _render_claude_resolution_suffix(spec, market_a, market_b)
    else:
        raise ValueError(f"Unsupported prompt family: {spec.family}")

    messages = (
        {"role": "user", "content": _join_blocks(reusable_prefix, request_suffix)},
    )
    return RenderedPrompt(
        family=spec.family,
        version=spec.version,
        adapter="claude_xml",
        reusable_prefix=reusable_prefix,
        request_suffix=request_suffix,
        messages=messages,
    )
