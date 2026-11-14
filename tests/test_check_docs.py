"""
Tests for the doc check's citation rule (.github/scripts/check_docs.py).

The README-proof convention (10 October 2026) has every capability name the
test that proves it. The doc check reads those citations and fails on one
that names no test. These tests are the evidence that it fails when it
should: each kind of dangling citation is refused on a small tree built
under tmp_path, and on the real tree a guard test that is renamed while the
Markdown still cites the old name is reported in every file that cites it.

Not an ADR guard, and outside --cov=episteme: the script is not part of the
package.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "check_docs.py"
_spec = importlib.util.spec_from_file_location("check_docs", SCRIPT)
assert _spec is not None and _spec.loader is not None
check_docs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_docs)

ALPHA = '''\
def test_top():
    pass


def helper():
    pass


class TestOne:
    def test_a(self):
        pass

    def test_b(self):
        pass

    def helper(self):
        pass


class TestTwo:
    def test_c(self):
        pass


class NotCollected:
    def test_hidden(self):
        pass
'''

BETA = '''\
async def test_other():
    pass
'''


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A repository root with two test files; returns a checker for one Markdown text."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_alpha.py").write_text(ALPHA, encoding="utf-8")
    (tmp_path / "tests" / "test_beta.py").write_text(BETA, encoding="utf-8")
    (tmp_path / "tests" / "conftest.py").write_text("def test_not_a_test_file(): pass\n")
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)
    monkeypatch.setattr(check_docs, "ELSEWHERE", set())

    def check(markdown: str, name: str = "DOC.md") -> tuple[int, list[str]]:
        path = tmp_path / name
        path.write_text(markdown, encoding="utf-8")
        errors: list[str] = []
        count = check_docs.citations(path, check_docs.defined_tests(), errors)
        return count, errors

    return check


def test_index_holds_what_pytest_would_collect_by_name(tree):
    index = check_docs.defined_tests()
    assert index == {
        "tests/test_alpha.py": (
            {"test_top"},
            {"TestOne": {"test_a", "test_b"}, "TestTwo": {"test_c"}},
        ),
        "tests/test_beta.py": ({"test_other"}, {}),
    }


def test_every_form_of_citation_resolves(tree):
    count, errors = tree(
        "A claim (`tests/test_alpha.py::TestOne::test_a`, `::test_b`,\n"
        "`::TestTwo::test_c`, and `::TestOne`), then at module level\n"
        "`tests/test_alpha.py::test_top`. Short for the file: `test_beta.py::test_other`.\n"
        "\n"
        "Tested in `tests/test_alpha.py`: one thing by `TestOne::test_a`, another by\n"
        "`::test_b`, and `test_top` and `TestTwo` by bare name. See `test_beta.py`.\n"
    )
    assert errors == []
    assert count == 12


@pytest.mark.parametrize(
    ("markdown", "expected"),
    [
        # A test renamed or removed while the Markdown still cites it.
        ("`tests/test_alpha.py::TestOne::test_gone`", "defines no TestOne::test_gone"),
        ("`tests/test_alpha.py::test_gone`", "defines no test_gone"),
        ("`tests/test_alpha.py::TestGone`", "defines no TestGone"),
        ("`tests/test_alpha.py::TestGone::test_a`", "defines no TestGone::test_a"),
        # A class left out of the id: the test exists, but not where the id says.
        ("`tests/test_alpha.py::test_a`", "tests/test_alpha.py defines no test_a"),
        ("`tests/test_alpha.py::TestTwo::test_a`", "defines no TestTwo::test_a"),
        ("`tests/test_beta.py::test_top`", "tests/test_beta.py defines no test_top"),
        # A test file renamed or removed.
        ("`tests/test_gamma.py::test_top`", "not a test file in tests/"),
        ("`test_gamma.py::test_top`", "not a test file in tests/"),
        ("`tests/test_gamma.py`", "not a test file in tests/"),
        ("`test_gamma.py`", "not a test file in tests/"),
        ("`tests/conftest.py::test_not_a_test_file`", "not a test file in tests/"),
        # Bare names nothing defines.
        ("`test_gone`", "a test no file in tests/ defines"),
        ("`TestGone`", "a test class no file in tests/ defines"),
        # Names pytest would not collect are not proof of anything.
        ("`tests/test_alpha.py::helper`", "defines no helper"),
        ("`tests/test_alpha.py::NotCollected::test_hidden`", "defines no NotCollected"),
        ("`test_hidden`", "a test no file in tests/ defines"),
        # A continuation with nothing to continue.
        ("`::test_top`", "no test file is cited before it"),
        ("`TestOne::test_a`", "no test file is cited before it"),
        # A continuation stays in the class cited before it.
        ("`tests/test_alpha.py::TestOne::test_a`, `::test_c`", "::TestOne defines no test_c"),
        ("`tests/test_alpha.py::TestOne::test_a`, `::test_top`", "::TestOne defines no test_top"),
        ("`tests/test_alpha.py`, `::test_a`", "tests/test_alpha.py defines no test_a"),
        # Ids the check cannot read are refused, not passed over.
        ("`tests/test_alpha.py::TestOne::test_a[case]`", "not a test id this check can read"),
        ("`tests/test_alpha.py::TestOne::test_a::more`", "not a test id this check can read"),
        ("`tests/test_alpha.py::`", "not a test id this check can read"),
        ("`episteme.core::EpistemicCore`", "not a test id this check can read"),
    ],
)
def test_a_citation_that_names_no_test_is_refused(tree, markdown, expected):
    count, errors = tree(f"Proved by {markdown}.\n")
    assert len(errors) == 1, errors
    assert expected in errors[0]
    assert errors[0].startswith("DOC.md:1: `")
    assert count == markdown.count("`") // 2


def test_a_missing_file_is_not_replaced_by_the_file_cited_before_it(tree):
    # `::test_top` would resolve against test_alpha.py; it must not, because
    # the file it continues from is the one that is gone.
    _, errors = tree("`tests/test_alpha.py::test_top`, then `tests/test_gamma.py`, `::test_top`.\n")
    assert len(errors) == 2
    assert "not a test file in tests/" in errors[0]
    assert "no test file is cited before it" in errors[1]


def test_a_class_cited_alone_is_the_class_a_continuation_means(tree):
    assert tree("`tests/test_alpha.py::TestTwo`, `::test_c`.\n") == (2, [])
    _, errors = tree("`tests/test_alpha.py::TestOne::test_a`, `::TestTwo`, `::test_a`.\n")
    assert len(errors) == 1
    assert "tests/test_alpha.py::TestTwo defines no test_a" in errors[0]


def test_a_bare_name_does_not_move_what_a_continuation_continues(tree):
    count, errors = tree("`tests/test_alpha.py::TestOne::test_a`, `TestTwo`, `test_other`, `::test_b`.\n")
    assert (count, errors) == (4, [])


def test_a_continuation_stays_with_a_class_that_is_gone(tree):
    # test_top exists at module level; it is not what `::test_top` means here.
    _, errors = tree("`tests/test_alpha.py::TestGone::test_a`, `::test_top`.\n")
    assert len(errors) == 2
    assert "tests/test_alpha.py::TestGone defines no test_top" in errors[1]


def test_one_dangling_test_is_one_problem(tree):
    # The class was named and exists, so what continues from it is still
    # read against that class and is not reported a second time.
    _, errors = tree("`tests/test_alpha.py::TestTwo::test_c`, `::TestOne::test_gone`, `::test_b`.\n")
    assert len(errors) == 1
    assert "defines no TestOne::test_gone" in errors[0]


def test_a_failed_citation_reports_its_line(tree):
    _, errors = tree("One.\n\nTwo `test_top`.\n\nThree `test_gone`.\n")
    assert errors == ["DOC.md:5: `test_gone` is a test no file in tests/ defines"]


def test_code_that_is_not_a_citation_is_left_alone(tree):
    count, errors = tree(
        "Run `pytest tests/test_alpha.py -k name`, or see `tests/test_<module>.py`,\n"
        "`TestingStrategy.md`, `testpaths`, `tests/`, `episteme/core.py` and `Test`.\n"
        "\n"
        "```bash\n"
        "pytest tests/test_gamma.py::test_gone\n"
        "`tests/test_gamma.py::test_gone`\n"
        "```\n"
        "\n"
        "~~~\n"
        "`test_gone`\n"
        "~~~\n"
    )
    assert errors == []
    assert count == 0


def test_a_test_in_another_repository_is_exempt_only_where_it_is_listed(tree, monkeypatch):
    monkeypatch.setattr(check_docs, "ELSEWHERE", {("DOC.md", "tests/test_theirs.py")})
    assert tree("Their `tests/test_theirs.py` pins the same property.\n") == (0, [])
    _, errors = tree("Their `tests/test_theirs.py` pins it.\n", name="OTHER.md")
    assert errors == ["OTHER.md:1: `tests/test_theirs.py` is not a test file in tests/"]
    _, errors = tree("Their `tests/test_theirs.py::test_x` pins it.\n")
    assert len(errors) == 1


class TestThisRepository:
    """The check on the real tree: clean as it stands, and not vacuously."""

    def run(self, index) -> tuple[dict[str, int], list[str]]:
        errors: list[str] = []
        counts = {
            check_docs.rel(path): check_docs.citations(path, index, errors)
            for path in check_docs.markdown_files()
        }
        return counts, errors

    def test_every_cited_test_resolves(self):
        counts, errors = self.run(check_docs.defined_tests())
        assert errors == []
        # The files that carry the convention are being read, not skipped.
        for name in ("README.md", "TestingStrategy.md", "CLAUDE.md"):
            assert counts[name] > 0, name

    def test_renaming_a_cited_guard_fails_the_check_wherever_it_is_cited(self):
        # ADR-0002's guard, as if renamed in tests/test_memory.py with the
        # Markdown left behind. The test file itself is not touched.
        index = check_docs.defined_tests()
        tests, classes = index["tests/test_memory.py"]
        renamed = dict(classes)
        renamed["TestBeliefRevision"] = classes["TestBeliefRevision"] - {
            "test_beliefs_never_deleted"
        }
        assert renamed["TestBeliefRevision"] != classes["TestBeliefRevision"]
        index["tests/test_memory.py"] = (tests, renamed)

        _, errors = self.run(index)
        assert errors, "a citation of a test that is gone went unreported"
        assert all("test_beliefs_never_deleted" in e for e in errors)
        cited_in = {e.split(":", 1)[0] for e in errors}
        assert {"README.md", "TestingStrategy.md", "CLAUDE.md"} <= cited_in

    def test_main_passes_as_the_tree_stands_and_fails_on_a_dangling_citation(
        self, capsys, monkeypatch
    ):
        assert check_docs.main() == 0
        assert capsys.readouterr().out.strip().endswith(" 0 problem(s)")

        index = check_docs.defined_tests()
        del index["tests/test_public_api.py"]
        monkeypatch.setattr(check_docs, "defined_tests", lambda: index)
        assert check_docs.main() == 1
        assert "`test_public_api.py` is not a test file in tests/" in capsys.readouterr().out
