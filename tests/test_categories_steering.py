"""`categories_file_default()` follows the run-start snapshot when a driver set one."""
from algua.research.categories import categories_file_default, load_categories


def test_categories_default_honors_steering_dir(monkeypatch, tmp_path):
    (tmp_path / "categories.txt").write_text("momentum market=us_equities\n# off\n")
    monkeypatch.setenv("ALGUA_STEERING_DIR", str(tmp_path))
    assert categories_file_default() == tmp_path / "categories.txt"
    assert load_categories() == ["momentum"]


def test_categories_default_without_steering_dir_is_repo_file(monkeypatch):
    monkeypatch.delenv("ALGUA_STEERING_DIR", raising=False)
    assert categories_file_default().as_posix().endswith(".opencode/categories.txt")
