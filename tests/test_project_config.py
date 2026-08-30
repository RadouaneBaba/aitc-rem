"""Reading `config/project.yaml`, and the one field that must never be lost.

`origin_policy` decides whether a recording made below `full` redaction may be
sent to a training-eligible model tier. It is the only setting in the file whose
value is a privacy decision, and it is the one YAML mangles.
"""

from __future__ import annotations

import pytest

from server.config.project import load_project_config


def write(tmp_path, body: str):
    path = tmp_path / "project.yaml"
    path.write_text(body, encoding="utf-8")
    return path


class TestOriginPolicy:
    def test_unquoted_off_is_honoured(self, tmp_path):
        """The exact line the refusal message tells a tester to write.

        YAML 1.1 reads `off` as the boolean `False`, and the old check was
        `if value in ORIGIN_POLICIES` -- which `False` is not -- so the setting
        was silently discarded and the config fell back to `warn`. Somebody
        followed the instruction to the letter, re-ran, and got the identical
        refusal with nothing on screen explaining why.
        """
        config = load_project_config(write(tmp_path, "origin_policy: off\n"))
        assert config.origin_policy == "off"

    def test_quoted_off_is_honoured_too(self, tmp_path):
        """Somebody who already knows about the YAML trap writes it this way."""
        config = load_project_config(write(tmp_path, 'origin_policy: "off"\n'))
        assert config.origin_policy == "off"

    @pytest.mark.parametrize("value", ["warn", "allowlist"])
    def test_the_ordinary_values_still_work(self, tmp_path, value):
        config = load_project_config(write(tmp_path, f"origin_policy: {value}\n"))
        assert config.origin_policy == value

    def test_an_absent_setting_keeps_the_safe_default(self, tmp_path):
        """Deleting the file must not turn the guard off."""
        config = load_project_config(write(tmp_path, "style: automation\n"))
        assert config.origin_policy == "warn"

    def test_a_typo_is_refused_rather_than_ignored(self, tmp_path):
        """The worse half of the original bug: a value nobody read.

        A privacy setting that silently means its default is indistinguishable
        from one nobody wrote, and both of this field's failure modes -- a typo
        and an unexpected YAML type -- used to look identical.
        """
        with pytest.raises(ValueError, match="origin_policy"):
            load_project_config(write(tmp_path, "origin_policy: warnn\n"))

    def test_on_is_refused_rather_than_guessed(self, tmp_path):
        """`on` is the boolean `True`, and it is not a policy in either
        direction. Guessing which one somebody meant is how a privacy setting
        comes to mean its opposite."""
        with pytest.raises(ValueError, match="not a setting"):
            load_project_config(write(tmp_path, "origin_policy: on\n"))
