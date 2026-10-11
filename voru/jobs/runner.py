"""Постановка заданий синтеза и GPU-worker.

Один worker = один провайдер (одна модель в памяти). Мастер пишется в
masters/<fingerprint>.wav — разные версии реплики физически не перезаписывают друг друга.
"""
from pathlib import Path

from voru.jobs.fingerprint import fingerprint
from voru.providers.base import SynthesisRequest, UnsupportedOption, VoiceRef
from voru.qa.audio import check_audio, verdict


def request_to_payload(request: SynthesisRequest, provider_name: str, normalization_revision: int) -> dict:
    voice = request.voice
    return {
        "provider": provider_name,
        "normalization_revision": normalization_revision,
        "text": request.text,
        "locale": request.locale,
        "player_gender": request.player_gender,
        "voice": {
            "voice_id": voice.voice_id,
            "voice_revision": voice.voice_revision,
            "reference_audio": str(voice.reference_audio) if voice.reference_audio else None,
            "reference_text": voice.reference_text,
        },
        "delivery_profile": request.delivery_profile,
        "generation_config": request.generation_config,
    }


def request_from_payload(payload: dict, output_path) -> SynthesisRequest:
    voice = payload["voice"]
    return SynthesisRequest(
        text=payload["text"],
        locale=payload["locale"],
        player_gender=payload["player_gender"],
        voice=VoiceRef(
            voice_id=voice["voice_id"],
            voice_revision=voice["voice_revision"],
            reference_audio=Path(voice["reference_audio"]) if voice["reference_audio"] else None,
            reference_text=voice["reference_text"],
        ),
        delivery_profile=payload["delivery_profile"],
        generation_config=payload["generation_config"],
        output_path=Path(output_path) if output_path else None,
    )


def enqueue_synthesis(queue, slot, provider, request, normalization_revision, validate=True) -> int:
    if validate:
        provider.validate(request)
    fp = fingerprint(provider.synthesis_input(request, normalization_revision))
    return queue.enqueue(slot, fp, request_to_payload(request, provider.name, normalization_revision))


def run_worker(queue, provider, worker_id: str, masters_dir, lease_s: float = 600) -> dict:
    """Обрабатывает задания провайдера, пока они есть. Прогресс сохраняется после каждой реплики.
    Каждый мастер сразу проходит автопроверку: брак — qa_failed, сомнительное — review_required."""
    stats = {"generated": 0, "failed": 0, "retried": 0, "qa_failed": 0, "review_required": 0}
    masters_dir = Path(masters_dir)
    while (job := queue.claim(worker_id, lease_s, provider=provider.name)) is not None:
        request = request_from_payload(job.payload, masters_dir / f"{job.fingerprint}.wav")
        try:
            actual = fingerprint(provider.synthesis_input(request, job.payload["normalization_revision"]))
            if actual != job.fingerprint:
                raise UnsupportedOption("fingerprint_mismatch", "входы синтеза изменились после постановки")
            result = provider.synthesize(request)
        except UnsupportedOption as err:
            queue.fail(job.job_id, worker_id, str(err), permanent=True)
        except Exception as err:  # noqa: BLE001 — любая ошибка модели: повтор по правилам очереди
            queue.fail(job.job_id, worker_id, f"{type(err).__name__}: {err}")
        else:
            queue.complete(job.job_id, worker_id, {
                "output_path": str(result.path),
                "duration_ms": result.duration_ms,
                "sample_rate": result.sample_rate,
                "model_revision": result.model_revision,
                "elapsed_s": round(result.elapsed_s, 3),
                "warnings": list(result.warnings),
            })
            if queue.get(job.job_id).state == "superseded":  # текст сменился, пока шёл синтез
                continue
            state, reason = verdict(check_audio(result.path, request.text))
            if state != "generated":
                queue.set_qa_state(job.job_id, state, reason)
            stats[state] += 1
            continue
        stats["failed" if queue.get(job.job_id).state == "failed" else "retried"] += 1
    return stats
