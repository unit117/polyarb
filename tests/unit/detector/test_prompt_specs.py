"""Tests for classifier prompt specs and renderers."""

from services.detector.prompt_specs import (
    LABEL_PROMPT_SPEC_V1,
    RESOLUTION_VECTOR_PROMPT_SPEC_V1,
    render_claude_prompt,
    render_generic_prompt,
    render_prompt,
    resolve_prompt_adapter,
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
        assert "Example 1:" in rendered.reusable_prefix
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
        assert len(rendered.messages) == 2
        assert rendered.messages[0]["role"] == "system"
        assert rendered.messages[1]["role"] == "user"
        assert "Rules:" in rendered.reusable_prefix
        assert "Example 1:" in rendered.reusable_prefix
        assert "Market A:" in rendered.request_suffix
        assert "Return strictly valid JSON with no additional text:" in rendered.reusable_prefix
        assert rendered.messages[0]["content"] == rendered.reusable_prefix
        assert rendered.messages[1]["content"] == rendered.request_suffix


class TestRenderClaudePrompt:
    def test_label_prompt_uses_xml_like_sections(self):
        rendered = render_claude_prompt(
            LABEL_PROMPT_SPEC_V1,
            {"question": "Will Team A win?", "description": "League final", "outcomes": ["Yes", "No"]},
            {"question": "Will Team B win?", "description": "League final", "outcomes": ["Yes", "No"]},
        )

        system_content = rendered.messages[0]["content"]
        user_content = rendered.messages[1]["content"]
        assert rendered.adapter == "claude_xml"
        assert rendered.messages[0]["role"] == "system"
        assert rendered.messages[1]["role"] == "user"
        assert "<role>" in system_content
        assert "<output_schema>" in system_content
        assert "<market_a>" in user_content
        assert "<market_b>" in user_content
        assert "Will Team A win?" in user_content

    def test_resolution_prompt_uses_cdata_for_xml_sensitive_content(self):
        rendered = render_claude_prompt(
            RESOLUTION_VECTOR_PROMPT_SPEC_V1,
            {"question": "Will A&B win <today>?", "outcomes": ["Yes", "No"]},
            {"question": "Will C win?", "outcomes": ["Yes", "No"]},
        )

        system_content = rendered.messages[0]["content"]
        user_content = rendered.messages[1]["content"]
        assert "<![CDATA[Will A&B win <today>?]]>" in user_content
        assert "<final_instruction>" in system_content


class TestPromptAdapterResolution:
    def test_auto_uses_claude_renderer_for_claude_models(self):
        rendered = render_prompt(
            LABEL_PROMPT_SPEC_V1,
            {"question": "Will A win?", "description": "", "outcomes": ["Yes", "No"]},
            {"question": "Will B win?", "description": "", "outcomes": ["Yes", "No"]},
            model="anthropic/claude-3.7-sonnet",
            prompt_adapter="auto",
        )

        assert rendered.adapter == "claude_xml"

    def test_explicit_override_beats_auto_detection(self):
        rendered = render_prompt(
            LABEL_PROMPT_SPEC_V1,
            {"question": "Will A win?", "description": "", "outcomes": ["Yes", "No"]},
            {"question": "Will B win?", "description": "", "outcomes": ["Yes", "No"]},
            model="anthropic/claude-3.7-sonnet",
            prompt_adapter="openai_generic",
        )

        assert rendered.adapter == "openai_generic"

    def test_resolve_prompt_adapter_rejects_invalid_values(self):
        try:
            resolve_prompt_adapter("gpt-4.1-mini", "bad_adapter")
        except ValueError as exc:
            assert "Unsupported prompt adapter" in str(exc)
        else:
            raise AssertionError("Expected ValueError for invalid prompt adapter")
