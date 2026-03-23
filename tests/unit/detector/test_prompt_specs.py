"""Tests for classifier prompt specs and renderers."""

from services.detector.prompt_specs import (
    LABEL_PROMPT_SPEC_V1,
    RESOLUTION_VECTOR_PROMPT_SPEC_V1,
    render_claude_prompt,
    render_generic_prompt,
)


class TestRenderGenericPrompt:
    def test_label_prompt_uses_system_and_user_split(self):
        rendered = render_generic_prompt(
            LABEL_PROMPT_SPEC_V1,
            {"question": "Will Arsenal win?", "description": "Match result", "outcomes": ["Yes", "No"]},
            {"question": "Will Arsenal reach semis?", "description": "Tournament", "outcomes": ["Yes", "No"]},
        )

        assert rendered.version == "label_v1"
        assert rendered.adapter == "openai_generic"
        assert len(rendered.messages) == 2
        assert rendered.messages[0]["role"] == "system"
        assert "dependency_type" in rendered.messages[0]["content"]
        assert "price-threshold markets" in rendered.reusable_prefix
        assert "Market A:" in rendered.request_suffix
        assert "Will Arsenal win?" in rendered.request_suffix
        assert "Will Arsenal reach semis?" in rendered.request_suffix

    def test_resolution_prompt_keeps_prefix_and_suffix_separate(self):
        rendered = render_generic_prompt(
            RESOLUTION_VECTOR_PROMPT_SPEC_V1,
            {"question": "Will Arsenal win the Champions League?", "outcomes": ["Yes", "No"]},
            {"question": "Will Arsenal reach the semifinal?", "outcomes": ["Yes", "No"]},
        )

        assert rendered.version == "resolution_v1"
        assert rendered.adapter == "openai_generic"
        assert len(rendered.messages) == 1
        assert rendered.messages[0]["role"] == "user"
        assert "Rules:" in rendered.reusable_prefix
        assert "Market A:" in rendered.request_suffix
        assert "Return strictly valid JSON with no additional text:" in rendered.request_suffix
        assert rendered.messages[0]["content"] == (
            f"{rendered.reusable_prefix}\n\n{rendered.request_suffix}"
        )


class TestRenderClaudePrompt:
    def test_label_prompt_uses_xml_like_sections(self):
        rendered = render_claude_prompt(
            LABEL_PROMPT_SPEC_V1,
            {"question": "Will Team A win?", "description": "League final", "outcomes": ["Yes", "No"]},
            {"question": "Will Team B win?", "description": "League final", "outcomes": ["Yes", "No"]},
        )

        content = rendered.messages[0]["content"]
        assert rendered.adapter == "claude_xml"
        assert "<role>" in content
        assert "<market_a>" in content
        assert "<market_b>" in content
        assert "<output_schema>" in content
        assert "Will Team A win?" in content

    def test_resolution_prompt_escapes_xml_sensitive_content(self):
        rendered = render_claude_prompt(
            RESOLUTION_VECTOR_PROMPT_SPEC_V1,
            {"question": "Will A&B win <today>?", "outcomes": ["Yes", "No"]},
            {"question": "Will C win?", "outcomes": ["Yes", "No"]},
        )

        content = rendered.messages[0]["content"]
        assert "Will A&amp;B win &lt;today&gt;?" in content
        assert "<final_instruction>" in content
