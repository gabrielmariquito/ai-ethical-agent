"""Tests for ethical_agent/install_record.py.

The record only ever makes the uninstaller more cautious or better informed,
so the important behaviours here are the *degenerate* ones: a missing file, a
corrupt file and a failed write all have to be non-events.
"""

import json

from ethical_agent.install_record import (
    RECORD_NAME,
    InstallRecord,
    describe_record,
    read_record,
    record_path,
    write_record,
)


def test_write_then_read_round_trips_every_field(tmp_path):
    written = InstallRecord(
        ollama_was_present_before=False,
        ollama_exe=r"C:\Programs\Ollama\ollama.exe",
        model_pulled="llama3.2:3b",
        env_keys=("OLLAMA_MODEL",),
        installer_download=r"C:\Temp\OllamaSetup.exe",
    )
    assert write_record(tmp_path, written) == record_path(tmp_path)

    read = read_record(tmp_path)
    assert read.ollama_was_present_before is False
    assert read.ollama_exe == written.ollama_exe
    assert read.model_pulled == "llama3.2:3b"
    assert read.env_keys == ("OLLAMA_MODEL",)
    assert read.installer_download == written.installer_download
    assert read.created_at  # stamped on first write


def test_missing_record_reads_as_no_information(tmp_path):
    assert read_record(tmp_path) is None


def test_corrupt_record_reads_as_no_information(tmp_path):
    # A half-written file must not be the reason an uninstall refuses to run.
    (tmp_path / RECORD_NAME).write_text('{"version": 1, "created_at":', encoding="utf-8")
    assert read_record(tmp_path) is None


def test_record_from_an_unknown_version_reads_as_no_information(tmp_path):
    (tmp_path / RECORD_NAME).write_text(json.dumps({"version": 99}), encoding="utf-8")
    assert read_record(tmp_path) is None


def test_record_with_wrong_field_types_degrades_instead_of_raising(tmp_path):
    (tmp_path / RECORD_NAME).write_text(
        json.dumps({"version": 1, "created_at": 5, "ollama_was_present_before": "sim",
                    "env_keys": "not-a-list"}),
        encoding="utf-8",
    )
    record = read_record(tmp_path)
    assert record is not None
    assert record.ollama_was_present_before is None  # "sim" is not a bool
    assert record.env_keys == ()


def test_write_merges_instead_of_overwriting(tmp_path):
    # The wizard learns these facts several methods apart -- a later
    # env_keys write must not erase the earlier ollama observation.
    write_record(tmp_path, InstallRecord(ollama_was_present_before=False))
    write_record(tmp_path, InstallRecord(model_pulled="llama3.2:3b"))
    write_record(tmp_path, InstallRecord(env_keys=("OLLAMA_MODEL",)))

    record = read_record(tmp_path)
    assert record.ollama_was_present_before is False
    assert record.model_pulled == "llama3.2:3b"
    assert record.env_keys == ("OLLAMA_MODEL",)


def test_merging_preserves_a_recorded_false_rather_than_treating_it_as_empty(tmp_path):
    # False is the *informative* value here ("nothing was installed before"),
    # so it must not be skipped as if it were an unset field.
    write_record(tmp_path, InstallRecord(ollama_was_present_before=False))
    write_record(tmp_path, InstallRecord(ollama_exe="/usr/local/bin/ollama"))
    assert read_record(tmp_path).ollama_was_present_before is False


def test_created_at_is_stamped_once_and_never_moved(tmp_path):
    write_record(tmp_path, InstallRecord())
    first = read_record(tmp_path).created_at
    write_record(tmp_path, InstallRecord(model_pulled="x"))
    assert read_record(tmp_path).created_at == first


def test_a_failed_write_returns_none_instead_of_raising(tmp_path):
    # Bookkeeping must never be the reason an install fails.
    missing = tmp_path / "does" / "not" / "exist"
    assert write_record(missing, InstallRecord(model_pulled="x")) is None


def test_describe_record_explains_what_the_installer_observed(tmp_path):
    assert "Não há registro" in describe_record(None)[0]

    write_record(tmp_path, InstallRecord(ollama_was_present_before=True))
    lines = describe_record(read_record(tmp_path))
    assert any("já existia" in line for line in lines)

    write_record(tmp_path, InstallRecord(ollama_was_present_before=False, model_pulled="llama3.2:3b"))
    lines = describe_record(read_record(tmp_path))
    assert any("Não havia Ollama localizável" in line for line in lines)
    assert any("llama3.2:3b" in line for line in lines)


def test_describe_record_never_leaks_an_api_key_value(tmp_path):
    write_record(tmp_path, InstallRecord(env_keys=("OLLAMA_API_KEY",)))
    lines = describe_record(read_record(tmp_path))
    # Only the key *name* is ever recorded, so there is nothing to leak.
    assert any("OLLAMA_API_KEY" in line for line in lines)
    assert "=" not in (tmp_path / RECORD_NAME).read_text(encoding="utf-8")
