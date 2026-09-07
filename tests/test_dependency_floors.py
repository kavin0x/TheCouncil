from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = (ROOT / "requirements.txt").read_text(encoding="utf-8")


def _declared_minimum(package: str) -> str:
    prefix = f"{package}>="
    for raw_line in REQUIREMENTS.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if line.startswith(prefix):
            return line[len(prefix) :]
    raise AssertionError(f"{package} lower bound not found in requirements.txt")


def test_python_requirement_floors_match_dependabot_bumps() -> None:
    floors = {
        "rich": "15.0.0",
        "fastapi": "0.141.1",
        "tavily-python": "0.7.26",
        "alembic": "1.18.5",
        "structlog": "26.1.0",
    }
    for package, expected in floors.items():
        assert _declared_minimum(package) == expected

    uvicorn_line = next(
        line.split("#", 1)[0].strip()
        for line in REQUIREMENTS.splitlines()
        if line.startswith("uvicorn[standard]>=")
    )
    assert uvicorn_line == "uvicorn[standard]>=0.52.4"
