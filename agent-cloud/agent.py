#!/usr/bin/env python3
"""
PolyArb Claude Agent — general-purpose automation agent.

Usage:
    # Interactive prompt
    python agent.py "Find all TODO comments in the codebase"

    # From stdin
    echo "Run the test suite" | python agent.py

    # With custom model
    CLAUDE_MODEL=claude-opus-4-6 python agent.py "Analyze the backtest results"
"""

import asyncio
import os
import sys

from claude_agent_sdk import query, ClaudeAgentOptions


async def run_agent(prompt: str) -> None:
    """Run a Claude agent with the given prompt."""
    work_dir = os.environ.get("AGENT_WORK_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    model = os.environ.get("CLAUDE_MODEL", None)
    permission_mode = os.environ.get("AGENT_PERMISSION_MODE", "bypassPermissions")

    options = ClaudeAgentOptions(
        allowed_tools=["Read", "Edit", "Write", "Bash", "Glob", "Grep", "Agent", "WebSearch", "WebFetch"],
        permission_mode=permission_mode,
        cwd=work_dir,
    )
    if model:
        options.model = model

    print(f"[agent] Working directory: {work_dir}")
    print(f"[agent] Permission mode: {permission_mode}")
    print(f"[agent] Prompt: {prompt[:200]}{'...' if len(prompt) > 200 else ''}")
    print("---")

    async for message in query(prompt=prompt, options=options):
        # Stream assistant text
        if hasattr(message, "content") and message.content:
            print(message.content, end="", flush=True)
        # Final result
        if hasattr(message, "result") and message.result:
            print(f"\n---\n[agent] Done. Result:\n{message.result}")


def main():
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
    elif not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()
    else:
        print("Usage: python agent.py <prompt>")
        print('  or:  echo "prompt" | python agent.py')
        sys.exit(1)

    if not prompt:
        print("Error: empty prompt")
        sys.exit(1)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    asyncio.run(run_agent(prompt))


if __name__ == "__main__":
    main()
