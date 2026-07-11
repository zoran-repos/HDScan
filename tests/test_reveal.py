from file_archive.webui import reveal


def test_reveal_in_explorer_builds_select_command(monkeypatch):
    calls = []
    monkeypatch.setattr(reveal.subprocess, "Popen", lambda cmd: calls.append(cmd))

    reveal.reveal_in_explorer(r"D:\Backup\photo.jpg")

    assert len(calls) == 1
    assert calls[0] == 'explorer /select,"D:\\Backup\\photo.jpg"'
