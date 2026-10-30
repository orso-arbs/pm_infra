import pytest


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A throwaway %LOCALAPPDATA%\\pm_infra so tests never touch the real install."""
    root = tmp_path / "home"
    root.mkdir()
    monkeypatch.setenv("PM_INFRA_HOME", str(root))
    return root


@pytest.fixture
def space(tmp_path, home):
    from pm_infra.spaces import Registry, create_space

    root = tmp_path / "Projects"
    root.mkdir()
    return create_space(root, "Projects", Registry())
