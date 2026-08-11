"""Tests for the alias system (executor shortcuts for rrg dispatch)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from rrg_cli.project import Project
from rrg_cli.alias import (
    list_aliases,
    set_alias,
    remove_alias,
    generate_shell_function,
    generate_shell_file,
    _normalize_alias_name,
)


def test_list_aliases_empty(ready_project: Project) -> None:
    assert list_aliases(ready_project) == {}


def test_set_and_list_alias(ready_project: Project) -> None:
    result = set_alias(ready_project, "grok-val", "grok")
    assert result["name"] == "grok-val"
    assert result["executor"] == "grok"
    aliases = list_aliases(ready_project)
    assert "grok-val" in aliases
    assert aliases["grok-val"]["executor"] == "grok"


def test_set_alias_with_model(ready_project: Project) -> None:
    set_alias(ready_project, "codex-val", "codex", model="gpt-5.6-terra")
    aliases = list_aliases(ready_project)
    assert aliases["codex-val"]["model"] == "gpt-5.6-terra"


def test_remove_alias(ready_project: Project) -> None:
    set_alias(ready_project, "grok-val", "grok")
    result = remove_alias(ready_project, "grok-val")
    assert result["removed"] is True
    assert "grok-val" not in list_aliases(ready_project)


def test_remove_nonexistent_alias(ready_project: Project) -> None:
    result = remove_alias(ready_project, "nonexistent")
    assert result["removed"] is False


def test_normalize_alias_name() -> None:
    assert _normalize_alias_name("grok-val") == "grok-val"
    assert _normalize_alias_name("grok val!") == "grok-val"
    assert _normalize_alias_name("test.val") == "test-val"
    assert _normalize_alias_name("") == "rrg-alias"


def test_generate_shell_function() -> None:
    func = generate_shell_function("grok-val", "grok")
    assert "grok-val()" in func
    assert "rrg dispatch" in func
    assert "--executor" in func
    assert "grok" in func
    assert "$@" in func


def test_generate_shell_function_with_model() -> None:
    func = generate_shell_function("codex-val", "codex", model="gpt-5.6-terra")
    assert "codex-val()" in func
    assert "gpt-5.6-terra" in func


def test_generate_shell_file(ready_project: Project) -> None:
    set_alias(ready_project, "grok-val", "grok")
    set_alias(ready_project, "codex-val", "codex", model="gpt-5.6-terra")
    content = generate_shell_file(ready_project)
    assert "RRG dispatch aliases" in content
    assert "grok-val()" in content
    assert "codex-val()" in content


def test_alias_overwrite(ready_project: Project) -> None:
    set_alias(ready_project, "my-val", "grok")
    set_alias(ready_project, "my-val", "claude")  # overwrite
    aliases = list_aliases(ready_project)
    assert aliases["my-val"]["executor"] == "claude"
