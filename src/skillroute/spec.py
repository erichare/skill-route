"""Validate SKILL.md bundles against the Agent Skills open specification.

The spec (https://agentskills.io/specification) defines the SKILL.md
frontmatter contract: required ``name`` and ``description`` fields with
concrete constraints, the optional ``license``, ``compatibility``,
``metadata``, and ``allowed-tools`` fields, and progressive-disclosure
guidance (keep the main file short, keep file references shallow). This
module checks those rules with no third-party dependencies, so it runs
everywhere SkillRoute does -- including in CI as a gate.

Findings are two-valued:

- ``error`` violates a spec MUST. A bundle with errors is not portable:
  spec-conforming clients are entitled to refuse it.
- ``warning`` violates a spec recommendation. The bundle still loads, but
  the guidance exists because real agents degrade on it (overlong files
  crowd the context window; thin descriptions route poorly).

Unknown top-level frontmatter fields are not flagged. The spec defines the
six fields above but does not forbid others, and SkillRoute's own extensions
(tags, relationships) are load-bearing. The spec's answer for portable extra
data is the ``metadata`` map; see docs/spec-compliance.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from skillroute.parser import FRONTMATTER_RE, MARKDOWN_LINK_RE, parse_frontmatter

SPEC_URL = "https://agentskills.io/specification"

ERROR = "error"
WARNING = "warning"
SEVERITIES = (ERROR, WARNING)

# Field constraints, straight from the spec's frontmatter table.
NAME_MAX = 64
NAME_RE = re.compile(r"\A[a-z0-9-]+\Z")
DESCRIPTION_MAX = 1024
COMPATIBILITY_MAX = 500

# Progressive-disclosure guidance. The spec recommends keeping SKILL.md under
# 500 lines and the activated load under ~5000 tokens; tokens are estimated
# at four characters each, which is the usual approximation for prose.
BODY_LINE_TARGET = 500
BODY_TOKEN_TARGET = 5000
TOKEN_CHAR_ESTIMATE = 4

# The spec's poor example ("Helps with PDFs.") is 16 characters; descriptions
# under this length almost never answer both "what it does" and "when to use
# it", which is what the description is for. Advisory only.
DESCRIPTION_SOFT_MIN = 50

SPEC_FIELDS = ("name", "description", "license", "compatibility", "metadata", "allowed-tools")


@dataclass(slots=True)
class SpecFinding:
    severity: str
    field: str
    message: str


@dataclass(slots=True)
class SkillSpecReport:
    skill_path: str
    bundle_path: str
    name: str | None
    findings: list[SpecFinding] = field(default_factory=list)

    @property
    def errors(self) -> list[SpecFinding]:
        return [finding for finding in self.findings if finding.severity == ERROR]

    @property
    def warnings(self) -> list[SpecFinding]:
        return [finding for finding in self.findings if finding.severity == WARNING]

    @property
    def ok(self) -> bool:
        return not self.findings


def validate_root(root: Path | str) -> list[SkillSpecReport]:
    """Validate every SKILL.md bundle discovered under a root directory."""
    root_path = Path(root).expanduser().resolve()
    return [
        validate_skill_file(skill_file)
        for skill_file in sorted(root_path.rglob("SKILL.md"))
        if skill_file.is_file()
    ]


def validate_target(path: Path | str) -> list[SkillSpecReport]:
    """Validate a SKILL.md file, a single bundle directory, or a whole root.

    A directory containing its own SKILL.md is one bundle; any other
    directory is scanned recursively. This is what `skillroute validate`
    applies to each of its path arguments.
    """
    target = Path(path).expanduser().resolve()
    if target.is_file():
        return [validate_skill_file(target)]
    if (target / "SKILL.md").is_file():
        return [validate_skill_file(target / "SKILL.md")]
    return validate_root(target)


def validate_skill_file(skill_file: Path | str) -> SkillSpecReport:
    skill_path = Path(skill_file).expanduser().resolve()
    report = SkillSpecReport(
        skill_path=str(skill_path),
        bundle_path=str(skill_path.parent),
        name=None,
    )
    text = skill_path.read_text(encoding="utf-8")
    if not FRONTMATTER_RE.match(text):
        report.findings.append(
            SpecFinding(
                ERROR,
                "frontmatter",
                "SKILL.md must open with a YAML frontmatter block (--- ... ---) "
                "declaring at least name and description",
            )
        )
        metadata: dict[str, Any] = {}
        body = text
    else:
        metadata, body = parse_frontmatter(text)

    _check_name(report, metadata.get("name"))
    _check_description(report, metadata.get("description"))
    _check_compatibility(report, metadata.get("compatibility"))
    _check_metadata_map(report, metadata.get("metadata"))
    _check_allowed_tools(report, metadata.get("allowed-tools"))
    _check_body(report, body)
    return report


def _check_name(report: SkillSpecReport, value: Any) -> None:
    if value is None or (isinstance(value, str) and not value.strip()):
        report.findings.append(SpecFinding(ERROR, "name", "name is required"))
        return
    if not isinstance(value, str):
        report.findings.append(
            SpecFinding(ERROR, "name", f"name must be a string, got {type(value).__name__}")
        )
        return
    name = value.strip()
    report.name = name
    if len(name) > NAME_MAX:
        report.findings.append(
            SpecFinding(ERROR, "name", f"name is {len(name)} characters; the maximum is {NAME_MAX}")
        )
    if not NAME_RE.match(name):
        report.findings.append(
            SpecFinding(
                ERROR,
                "name",
                "name may only contain lowercase letters, numbers, and hyphens",
            )
        )
    if name.startswith("-") or name.endswith("-"):
        report.findings.append(
            SpecFinding(ERROR, "name", "name must not start or end with a hyphen")
        )
    if "--" in name:
        report.findings.append(
            SpecFinding(ERROR, "name", "name must not contain consecutive hyphens")
        )
    directory = Path(report.bundle_path).name
    if name != directory:
        report.findings.append(
            SpecFinding(
                ERROR,
                "name",
                f"name {name!r} must match the parent directory name {directory!r}",
            )
        )


def _check_description(report: SkillSpecReport, value: Any) -> None:
    if value is None or (isinstance(value, str) and not value.strip()):
        report.findings.append(SpecFinding(ERROR, "description", "description is required"))
        return
    if not isinstance(value, str):
        report.findings.append(
            SpecFinding(
                ERROR,
                "description",
                f"description must be a string, got {type(value).__name__}",
            )
        )
        return
    description = value.strip()
    if len(description) > DESCRIPTION_MAX:
        report.findings.append(
            SpecFinding(
                ERROR,
                "description",
                f"description is {len(description)} characters; the maximum is {DESCRIPTION_MAX}",
            )
        )
    if len(description) < DESCRIPTION_SOFT_MIN:
        report.findings.append(
            SpecFinding(
                WARNING,
                "description",
                "description is short; the spec recommends describing both what the "
                "skill does and when to use it, with keywords an agent can match on",
            )
        )


def _check_compatibility(report: SkillSpecReport, value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        report.findings.append(
            SpecFinding(
                ERROR,
                "compatibility",
                f"compatibility must be a string, got {type(value).__name__}",
            )
        )
        return
    if len(value.strip()) > COMPATIBILITY_MAX:
        report.findings.append(
            SpecFinding(
                ERROR,
                "compatibility",
                f"compatibility is {len(value.strip())} characters; the maximum is "
                f"{COMPATIBILITY_MAX}",
            )
        )


def _check_metadata_map(report: SkillSpecReport, value: Any) -> None:
    if value is None:
        return
    # parse_simple_yaml leaves a bare `metadata:` line as an empty list.
    if value == []:
        return
    if not isinstance(value, dict):
        report.findings.append(
            SpecFinding(
                ERROR,
                "metadata",
                f"metadata must be a key-value mapping, got {type(value).__name__}",
            )
        )
        return
    for key, item in value.items():
        if not isinstance(item, str):
            rendered = str(item).lower() if isinstance(item, bool) else str(item)
            report.findings.append(
                SpecFinding(
                    ERROR,
                    "metadata",
                    f"metadata value {key!r} must be a string; quote it "
                    f"(e.g. {key}: \"{rendered}\")",
                )
            )


def _check_allowed_tools(report: SkillSpecReport, value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        report.findings.append(
            SpecFinding(
                ERROR,
                "allowed-tools",
                "allowed-tools must be a space-separated string "
                "(e.g. 'Bash(git:*) Read'), not a YAML list",
            )
        )


def _check_body(report: SkillSpecReport, body: str) -> None:
    lines = body.splitlines()
    if len(lines) > BODY_LINE_TARGET:
        report.findings.append(
            SpecFinding(
                WARNING,
                "body",
                f"SKILL.md body is {len(lines)} lines; the spec recommends under "
                f"{BODY_LINE_TARGET} -- move detail into referenced files",
            )
        )
    estimated_tokens = len(body) // TOKEN_CHAR_ESTIMATE
    if estimated_tokens > BODY_TOKEN_TARGET:
        report.findings.append(
            SpecFinding(
                WARNING,
                "body",
                f"SKILL.md body is ~{estimated_tokens} tokens (estimated); the spec "
                f"recommends under {BODY_TOKEN_TARGET} once activated",
            )
        )
    _check_references(report, body)


def _check_references(report: SkillSpecReport, body: str) -> None:
    flagged: set[str] = set()
    for match in MARKDOWN_LINK_RE.finditer(body):
        target = match.group("target").split("#", 1)[0].strip()
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        if target.startswith(("/", "..")):
            flagged.add(f"reference {target!r} points outside the skill bundle")
            continue
        # "One level deep from SKILL.md": references/REFERENCE.md is fine,
        # references/legal/REFERENCE.md asks the agent to follow a chain.
        parent_dirs = len(Path(target).parts) - 1
        if parent_dirs > 1:
            flagged.add(
                f"reference {target!r} is more than one level deep; the spec "
                "recommends keeping file references one level from SKILL.md"
            )
    for message in sorted(flagged):
        report.findings.append(SpecFinding(WARNING, "references", message))


def summarize_reports(reports: list[SkillSpecReport]) -> dict[str, int]:
    return {
        "bundles": len(reports),
        "ok": sum(1 for report in reports if report.ok),
        "errors": sum(len(report.errors) for report in reports),
        "warnings": sum(len(report.warnings) for report in reports),
    }


def report_to_dict(report: SkillSpecReport) -> dict[str, Any]:
    return {
        "skill_path": report.skill_path,
        "bundle_path": report.bundle_path,
        "name": report.name,
        "ok": report.ok,
        "findings": [
            {"severity": finding.severity, "field": finding.field, "message": finding.message}
            for finding in report.findings
        ],
    }


def render_report_lines(report: SkillSpecReport) -> list[str]:
    """One line per finding; nothing for a clean bundle."""
    return [
        f"  {finding.severity}[{finding.field}]: {finding.message}"
        for finding in report.findings
    ]
