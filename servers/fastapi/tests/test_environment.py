import pytest

from utils.environment import load_studio_environment


def test_explicit_source_process_precedence_and_no_secret_interpolation(tmp_path, monkeypatch):
    source = tmp_path / 'selected.env'
    source.write_text('STUDIO_API_KEY=${literal}\nAZURE_OPENAI_API_KEY=file-secret\n', encoding='utf-8')
    monkeypatch.setenv('STUDIO_ENV_FILE', str(source))
    monkeypatch.delenv('STUDIO_API_KEY', raising=False)
    monkeypatch.setenv('AZURE_OPENAI_API_KEY', 'process-secret')
    load_studio_environment()
    import os
    assert os.environ['STUDIO_API_KEY'] == '${literal}'
    assert os.environ['AZURE_OPENAI_API_KEY'] == 'process-secret'


def test_parent_supplied_environment_skips_all_files(monkeypatch):
    monkeypatch.setenv('STUDIO_ENV_FILE', '')
    monkeypatch.delenv('AZURE_OPENAI_API_KEY', raising=False)
    load_studio_environment()
    import os
    assert 'AZURE_OPENAI_API_KEY' not in os.environ


def test_duplicate_key_error_is_redacted(tmp_path, monkeypatch):
    source = tmp_path / 'selected.env'
    source.write_text('STUDIO_API_KEY=secret-one\nSTUDIO_API_KEY=secret-two\n', encoding='utf-8')
    monkeypatch.setenv('STUDIO_ENV_FILE', str(source))
    with pytest.raises(ValueError) as error:
        load_studio_environment()
    assert 'STUDIO_API_KEY' in str(error.value) and 'secret-one' not in str(error.value)
