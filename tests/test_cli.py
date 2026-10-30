import json

from seance.cli import main
from seance.config import load_config


def _setup(tmp_path, url):
    home = tmp_path / "Seance"
    assert main(["init", "--home", str(home)]) == 0
    cfg_path = home / "config.toml"
    text = cfg_path.read_text(encoding="utf-8").replace("http://localhost:11434", url)
    cfg_path.write_text(text, encoding="utf-8")
    return ["--config", str(cfg_path)]


def test_full_cli_flow(tmp_path, fake_ollama, samples, capsys):
    url, calls = fake_ollama
    c = _setup(tmp_path, url)
    cfg = load_config(c[1])
    assert cfg.whisper_device == "cpu"

    assert main(c + ["doctor"]) == 0
    out = capsys.readouterr().out
    assert "Gemma replied" in out and "All good" in out and "semantic search on" in out

    assert main(c + ["add", str(samples / "grandma_the_house_in_kerala.txt"), "-s", "Grandma"]) == 0
    assert main(c + ["add", str(samples / "grandpa_coming_to_dubai.txt"), "-s", "Grandpa",
                     "--title", "Coming to Dubai"]) == 0
    out = capsys.readouterr().out
    assert "In their words" in out and "Gemma took" in out

    assert main(c + ["list"]) == 0
    out = capsys.readouterr().out
    assert "Coming to Dubai" in out and "Grandma" in out

    assert main(c + ["show", "coming to dubai", "--transcript"]) == 0
    assert "[00:05]" in capsys.readouterr().out

    assert main(c + ["ask", "how", "did", "he", "cross", "the", "Creek", "by", "abra"]) == 0
    out = capsys.readouterr().out
    assert "Grandpa" in out and "“" in out

    assert main(c + ["person", "Grandma", "--relation", "Dad's mother", "--years", "1940–2021"]) == 0
    assert main(c + ["people"]) == 0
    assert "Dad's mother" in capsys.readouterr().out

    assert main(c + ["questions", "-s", "Grandpa"]) == 0
    assert "Next time you sit with Grandpa" in capsys.readouterr().out

    assert main(c + ["ofrenda", "--title", "The Thomas family"]) == 0
    html = (tmp_path / "Seance" / "ofrenda.html").read_text(encoding="utf-8")
    assert "The Thomas family" in html and "Dad&#x27;s mother" in html

    assert main(c + ["reindex"]) == 0
    assert "EmbeddingGemma" in capsys.readouterr().out

    assert main(c + ["stats"]) == 0
    out = capsys.readouterr().out
    assert "Stories:                 2 from 2 people" in out and "Quotes rejected" in out

    assert main(c + ["play", "coming to dubai", "--moment", "1"]) == 0
    assert "no audio for this story" in capsys.readouterr().out

    assert main(c + ["remove", "coming to dubai"]) == 0
    assert "Moved" in capsys.readouterr().out
    assert main(c + ["list"]) == 0
    assert "Coming to Dubai" not in capsys.readouterr().out

    chat_calls = [b for m, p, b in calls if p == "/api/chat"]
    assert chat_calls and all(b["model"] == "gemma4:e4b" and b["format"] for b in chat_calls)
    assert any(p == "/api/embed" for _, p, _ in calls)


def test_doctor_when_ollama_down(tmp_path, capsys):
    c = _setup(tmp_path, "http://127.0.0.1:9")
    assert main(c + ["doctor"]) == 1
    assert "Can't reach Ollama" in capsys.readouterr().out


def test_commands_need_an_archive(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SEANCE_HOME", str(tmp_path / "nowhere"))
    monkeypatch.chdir(tmp_path)
    import pytest
    with pytest.raises(SystemExit):
        main(["list"])


def test_ask_on_empty_archive(tmp_path, fake_ollama, capsys):
    url, _ = fake_ollama
    c = _setup(tmp_path, url)
    assert main(c + ["ask", "anything"]) == 1
    assert "archive is empty" in capsys.readouterr().out
