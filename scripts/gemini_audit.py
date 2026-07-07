"""Compatibility wrapper for the code-audit script (now Kimi/Moonshot-default).

Prefer:
    python -m scripts.deepseek_audit
"""

from scripts.deepseek_audit import main


if __name__ == "__main__":
    main()
