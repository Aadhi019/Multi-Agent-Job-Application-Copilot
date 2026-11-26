from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent


def load_prompt(agent_name: str, version: str = "v1") -> str:
    """Load a versioned prompt template from backend/app/agents/prompts/."""
    path = PROMPTS_DIR / f"{agent_name}_{version}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()
