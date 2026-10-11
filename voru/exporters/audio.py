"""Кодирование WAV-мастера в OGG Vorbis для клиента (дизайн §11).

ffmpeg берётся из пакета imageio-ffmpeg (статическая сборка, без системной установки).
Длительность читается из готового OGG, а не из мастера. Файл появляется атомарно.
"""
import os
import subprocess
from pathlib import Path

VORBIS_QUALITY = "4"  # ~64–80 кбит/с моно; уточнить по громкости/качеству на пилоте


class EncodeError(RuntimeError):
    pass


def ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def encode_ogg(src_wav, dst_ogg) -> float:
    """Кодирует и проверяет контейнер; возвращает длительность готового файла в секундах."""
    from mutagen import MutagenError
    from mutagen.oggvorbis import OggVorbis

    dst = Path(dst_ogg)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f".{dst.name}.{os.getpid()}.tmp.ogg")
    try:
        proc = subprocess.run(
            [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src_wav),
             "-vn", "-ac", "1", "-c:a", "libvorbis", "-q:a", VORBIS_QUALITY, "-map_metadata", "-1",
             # bitexact: детерминированный serial Ogg-потока и без версии ffmpeg в тегах —
             # одинаковый мастер даёт байт-в-байт одинаковый файл
             "-fflags", "+bitexact", "-flags:a", "+bitexact", str(tmp)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise EncodeError(f"{src_wav}: ffmpeg failed: {proc.stderr.strip()[:300]}")
        try:
            duration = OggVorbis(str(tmp)).info.length
        except MutagenError as err:
            raise EncodeError(f"{src_wav}: encoded file is not Ogg Vorbis: {err}") from err
        if duration <= 0:
            raise EncodeError(f"{src_wav}: encoded file has zero duration")
        os.replace(tmp, dst)
        return duration
    finally:
        if tmp.exists():
            tmp.unlink()
