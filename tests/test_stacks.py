from pathlib import Path

import pytest

from priors import stacks


@pytest.fixture(autouse=True)
def _clear_cache():
    stacks._detect_at_root.cache_clear()
    yield
    stacks._detect_at_root.cache_clear()


def test_no_root(tmp_path):
    assert stacks.detect_stacks(tmp_path) == set()


def test_pyproject_python(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["django>=5"]\n'
    )
    out = stacks.detect_stacks(tmp_path)
    assert "python" in out
    assert "django" in out


def test_package_json_node_typescript(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"dependencies": {"react": "^18", "typescript": "^5"}}'
    )
    out = stacks.detect_stacks(tmp_path)
    assert {"node", "react", "typescript"}.issubset(out)


def test_go(tmp_path):
    (tmp_path / "go.mod").write_text("module x\n")
    assert "go" in stacks.detect_stacks(tmp_path)


def test_rust(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname = \"x\"\n")
    assert "rust" in stacks.detect_stacks(tmp_path)


def test_java_spring(tmp_path):
    (tmp_path / "pom.xml").write_text(
        "<project><dependencies><dependency><groupId>org.springframework</groupId>"
        "</dependency></dependencies></project>"
    )
    out = stacks.detect_stacks(tmp_path)
    assert {"java", "spring"}.issubset(out)


def test_terraform_and_docker(tmp_path):
    (tmp_path / "main.tf").write_text("")
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    (tmp_path / ".git").mkdir()
    out = stacks.detect_stacks(tmp_path)
    assert {"terraform", "docker"}.issubset(out)


def test_github_actions(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    assert "github-actions" in stacks.detect_stacks(tmp_path)


def test_find_root_from_subdir(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    assert stacks.find_project_root(sub) == tmp_path.resolve()
