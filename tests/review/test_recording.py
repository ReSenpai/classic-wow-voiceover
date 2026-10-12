"""Стенд записи реплик: страница со сценарием, запись в браузере, сохранение в папку голоса."""
import io
import json
import threading
import urllib.error
import urllib.request
import wave

import pytest

from voru.review.recording import RecordingItem, file_name, make_server, recording_items


def wav_bytes(seconds=0.5, rate=48000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((b"\x00\x20" + b"\x00\xe0") * int(rate * seconds / 2))  # ±8192 — слышимый сигнал
    return buf.getvalue()


ITEMS = [
    RecordingItem(name="488-accept-m", title="Квест 488 · взятие", note="игрок — мужчина",
                  spoken_text="В+ижу, ты работ+ёнку +ищешь?"),
    RecordingItem(name="489-complete", title="Квест 489 · сдача", note="", spoken_text="Ну чт+о т+ы за л+апочка!"),
]


@pytest.fixture
def server(tmp_path):
    srv = make_server(ITEMS, tmp_path / "rec", port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", tmp_path / "rec"
    srv.shutdown()
    srv.server_close()


def request(url, data=None, method=None):
    req = urllib.request.Request(url, data=data, method=method)
    with urllib.request.urlopen(req) as resp:
        return resp.status, resp.read()


def test_file_names_from_slots():
    assert file_name(488, "accept", "m") == "488-accept-m"
    assert file_name(489, "complete", None) == "489-complete"


def test_page_shows_script_with_stress_highlight(server):
    url, _ = server

    status, body = request(url + "/")

    page = body.decode("utf-8")
    assert status == 200
    assert "488-accept-m" in page and "Ну чт" in page
    assert "<b>и</b>" in page  # «В+ижу» — ударная гласная выделена
    assert "+" not in page.split("<main>")[1].split("<script>")[0]


def test_upload_is_saved_as_wav_and_listed(server):
    url, rec = server

    status, _ = request(url + "/save/488-accept-m", data=wav_bytes(), method="PUT")

    assert status == 200
    with wave.open(str(rec / "488-accept-m.wav")) as w:
        assert w.getnchannels() == 1
        assert w.getnframes() > 0
    _, listing = request(url + "/list")
    assert json.loads(listing)["488-accept-m"]["seconds"] == pytest.approx(0.5, abs=0.05)
    _, audio = request(url + "/audio/488-accept-m.wav")
    assert audio[:4] == b"RIFF"


def test_rerecording_overwrites(server):
    url, rec = server
    request(url + "/save/489-complete", data=wav_bytes(0.5), method="PUT")

    request(url + "/save/489-complete", data=wav_bytes(1.0), method="PUT")

    with wave.open(str(rec / "489-complete.wav")) as w:
        assert w.getnframes() / w.getframerate() == pytest.approx(1.0, abs=0.05)


@pytest.mark.parametrize("name", ["..%2F..%2Fevil", "unknown-line", "488-accept-m.wav"])
def test_only_script_names_can_be_saved(server, name):
    url, rec = server

    with pytest.raises(urllib.error.HTTPError) as err:
        request(url + f"/save/{name}", data=wav_bytes(), method="PUT")

    assert err.value.code in (400, 404)
    assert not any(rec.glob("*")) if rec.exists() else True


def test_silent_upload_is_rejected(server):
    """Регрессия: Chrome писал не тот микрофон — файл сохранился с пиком −76 дБ."""
    url, rec = server
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(b"\x05\x00" * 48000)

    with pytest.raises(urllib.error.HTTPError) as err:
        request(url + "/save/489-complete", data=buf.getvalue(), method="PUT")

    assert err.value.code == 400
    assert "тишина" in err.value.read().decode("utf-8")
    assert not (rec / "489-complete.wav").exists()


def test_broken_upload_is_rejected_and_keeps_previous(server):
    url, rec = server
    request(url + "/save/489-complete", data=wav_bytes(0.5), method="PUT")

    with pytest.raises(urllib.error.HTTPError) as err:
        request(url + "/save/489-complete", data=b"not audio", method="PUT")

    assert err.value.code == 400
    with wave.open(str(rec / "489-complete.wav")) as w:
        assert w.getnframes() > 0


def test_items_for_voice_from_pilot():
    from voru.pipeline import PILOT_CORPUS

    items = recording_items([PILOT_CORPUS], "satyr-male")

    assert [i.name for i in items] == ["488-accept-f", "488-accept-m", "488-complete", "489-complete"]
    assert all(i.spoken_text for i in items)
