from __future__ import annotations

from pathlib import Path

import pytest

from skillroute.spec import (
    ERROR,
    WARNING,
    summarize_reports,
    validate_root,
    validate_skill_file,
    validate_target,
)

GOOD_DESCRIPTION = "Extracts text and tables from PDF files. Use when working with PDF documents."


def write_skill(root: Path, directory: str, text: str) -> Path:
    bundle = root / directory
    bundle.mkdir(parents=True, exist_ok=True)
    skill_file = bundle / "SKILL.md"
    skill_file.write_text(text, encoding="utf-8")
    return skill_file


def minimal_bundle(name: str, description: str = GOOD_DESCRIPTION) -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\nInstructions.\n"


def fields(report, severity=None) -> list[tuple[str, str]]:
    return [
        (finding.severity, finding.field)
        for finding in report.findings
        if severity is None or finding.severity == severity
    ]


def test_valid_minimal_bundle_is_clean(tmp_path: Path) -> None:
    skill_file = write_skill(tmp_path, "pdf-processing", minimal_bundle("pdf-processing"))
    report = validate_skill_file(skill_file)
    assert report.ok
    assert report.name == "pdf-processing"


def test_valid_full_bundle_is_clean(tmp_path: Path) -> None:
    text = (
        "---\n"
        "name: pdf-processing\n"
        f"description: {GOOD_DESCRIPTION}\n"
        "license: Apache-2.0\n"
        "compatibility: Requires Python 3.14+ and uv\n"
        "metadata:\n"
        "  author: example-org\n"
        '  version: "1.0"\n'
        "allowed-tools: Bash(git:*) Bash(jq:*) Read\n"
        "---\n\n# PDF Processing\n\nSee [the reference](references/REFERENCE.md).\n"
    )
    skill_file = write_skill(tmp_path, "pdf-processing", text)
    assert validate_skill_file(skill_file).ok


def test_missing_frontmatter_is_an_error(tmp_path: Path) -> None:
    skill_file = write_skill(tmp_path, "pdf-processing", "# No frontmatter\n\nJust prose.\n")
    report = validate_skill_file(skill_file)
    assert (ERROR, "frontmatter") in fields(report)
    assert (ERROR, "name") in fields(report)
    assert (ERROR, "description") in fields(report)


@pytest.mark.parametrize(
    "name",
    ["PDF-Processing", "-pdf", "pdf-", "pdf--processing", "pdf_processing", "Pdf"],
)
def test_invalid_names_are_errors(tmp_path: Path, name: str) -> None:
    skill_file = write_skill(tmp_path, "pdf-processing", minimal_bundle(name))
    report = validate_skill_file(skill_file)
    assert (ERROR, "name") in fields(report), name


def test_name_over_64_characters_is_an_error(tmp_path: Path) -> None:
    name = "a" * 65
    skill_file = write_skill(tmp_path, name, minimal_bundle(name))
    assert (ERROR, "name") in fields(validate_skill_file(skill_file))


def test_name_must_match_parent_directory(tmp_path: Path) -> None:
    skill_file = write_skill(tmp_path, "actual-dir", minimal_bundle("other-name"))
    report = validate_skill_file(skill_file)
    assert (ERROR, "name") in fields(report)
    assert "actual-dir" in report.findings[-1].message


def test_non_string_name_is_an_error(tmp_path: Path) -> None:
    skill_file = write_skill(tmp_path, "pdf-processing", "---\nname: [a, b]\ndescription: x\n---\n")
    assert (ERROR, "name") in fields(validate_skill_file(skill_file))


def test_non_string_description_and_compatibility_are_errors(tmp_path: Path) -> None:
    text = (
        "---\n"
        "name: pdf-processing\n"
        "description: [not, a, string]\n"
        "compatibility: [also, not]\n"
        "---\n"
    )
    skill_file = write_skill(tmp_path, "pdf-processing", text)
    report = validate_skill_file(skill_file)
    assert (ERROR, "description") in fields(report)
    assert (ERROR, "compatibility") in fields(report)


def test_bare_metadata_line_is_not_an_error(tmp_path: Path) -> None:
    # parse_simple_yaml represents a bare `metadata:` key as an empty list;
    # an empty map declares nothing and violates nothing.
    text = minimal_bundle("pdf-processing").replace("---\n\n", "metadata:\n---\n\n", 1)
    skill_file = write_skill(tmp_path, "pdf-processing", text)
    assert validate_skill_file(skill_file).ok


def test_oversized_body_token_estimate_is_a_warning(tmp_path: Path) -> None:
    body = "\n" + ("detailed guidance for every edge case " * 600)
    skill_file = write_skill(tmp_path, "pdf-processing", minimal_bundle("pdf-processing") + body)
    report = validate_skill_file(skill_file)
    assert (WARNING, "body") in fields(report)
    assert any("tokens" in finding.message for finding in report.warnings)


def test_description_required_and_bounded(tmp_path: Path) -> None:
    missing = write_skill(tmp_path / "a", "no-description", "---\nname: no-description\n---\n")
    assert (ERROR, "description") in fields(validate_skill_file(missing))

    long_dir = "long-description"
    overlong = write_skill(
        tmp_path / "b", long_dir, minimal_bundle(long_dir, description="x" * 1025)
    )
    assert (ERROR, "description") in fields(validate_skill_file(overlong))


def test_short_description_is_a_warning(tmp_path: Path) -> None:
    skill_file = write_skill(tmp_path, "pdf-processing", minimal_bundle("pdf-processing", "Helps with PDFs."))
    report = validate_skill_file(skill_file)
    assert fields(report, ERROR) == []
    assert (WARNING, "description") in fields(report)


def test_compatibility_over_500_characters_is_an_error(tmp_path: Path) -> None:
    text = minimal_bundle("pdf-processing").replace(
        "---\n\n", f"compatibility: {'x' * 501}\n---\n\n", 1
    )
    skill_file = write_skill(tmp_path, "pdf-processing", text)
    assert (ERROR, "compatibility") in fields(validate_skill_file(skill_file))


def test_metadata_values_must_be_strings(tmp_path: Path) -> None:
    text = minimal_bundle("pdf-processing").replace(
        "---\n\n", "metadata:\n  author: example-org\n  stable: true\n---\n\n", 1
    )
    skill_file = write_skill(tmp_path, "pdf-processing", text)
    report = validate_skill_file(skill_file)
    assert (ERROR, "metadata") in fields(report)
    assert "stable" in report.findings[0].message


def test_metadata_must_be_a_mapping(tmp_path: Path) -> None:
    text = minimal_bundle("pdf-processing").replace("---\n\n", "metadata: just-a-string\n---\n\n", 1)
    skill_file = write_skill(tmp_path, "pdf-processing", text)
    assert (ERROR, "metadata") in fields(validate_skill_file(skill_file))


def test_allowed_tools_must_be_a_string(tmp_path: Path) -> None:
    text = minimal_bundle("pdf-processing").replace(
        "---\n\n", "allowed-tools:\n  - Bash(git:*)\n  - Read\n---\n\n", 1
    )
    skill_file = write_skill(tmp_path, "pdf-processing", text)
    assert (ERROR, "allowed-tools") in fields(validate_skill_file(skill_file))


def test_overlong_body_is_a_warning(tmp_path: Path) -> None:
    body = "\n".join(f"line {index} of guidance" for index in range(600))
    skill_file = write_skill(tmp_path, "pdf-processing", minimal_bundle("pdf-processing") + body)
    report = validate_skill_file(skill_file)
    assert (WARNING, "body") in fields(report)
    assert fields(report, ERROR) == []


def test_deep_and_escaping_references_are_warnings(tmp_path: Path) -> None:
    body = (
        "\nSee [deep](references/legal/REFERENCE.md), "
        "[outside](../shared/common.md), and [absolute](/etc/passwd).\n"
    )
    skill_file = write_skill(tmp_path, "pdf-processing", minimal_bundle("pdf-processing") + body)
    report = validate_skill_file(skill_file)
    messages = [finding.message for finding in report.findings if finding.field == "references"]
    assert len(messages) == 3
    assert fields(report, ERROR) == []


def test_urls_and_anchors_are_not_file_references(tmp_path: Path) -> None:
    body = "\nSee [the spec](https://agentskills.io/specification#frontmatter) and [mail](mailto:a@b.c).\n"
    skill_file = write_skill(tmp_path, "pdf-processing", minimal_bundle("pdf-processing") + body)
    assert validate_skill_file(skill_file).ok


def test_validate_target_accepts_file_bundle_dir_and_root(tmp_path: Path) -> None:
    skill_file = write_skill(tmp_path / "root", "pdf-processing", minimal_bundle("pdf-processing"))
    assert len(validate_target(skill_file)) == 1
    assert len(validate_target(skill_file.parent)) == 1
    assert len(validate_target(tmp_path)) == 1
    assert validate_root(tmp_path / "root")[0].ok


def test_summarize_reports(tmp_path: Path) -> None:
    write_skill(tmp_path, "good-skill", minimal_bundle("good-skill"))
    write_skill(tmp_path, "bad-skill", "# nothing\n")
    summary = summarize_reports(validate_root(tmp_path))
    assert summary == {"bundles": 2, "ok": 1, "errors": 3, "warnings": 0}


def test_repo_example_skills_are_spec_compliant() -> None:
    examples = Path(__file__).parent.parent / "examples" / "skills"
    reports = validate_root(examples)
    assert reports, "expected the repo's example skills to be discovered"
    for report in reports:
        assert report.errors == [], f"{report.skill_path}: {report.errors}"
