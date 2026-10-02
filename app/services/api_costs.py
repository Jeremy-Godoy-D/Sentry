"""Estimaciones locales del consumo de las APIs de análisis."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


RECOMMENDED_API_MODELS = {
    "transcription": {"deepgram": "nova-3"},
    "analysis": {"gemini": "gemini-3.5-flash", "deepseek": "deepseek-flash",
                 "groq": "openai/gpt-oss-120b"},
}


# USD, modalidad estándar de pago por uso. Las tarifas se aplican automáticamente
# a solicitudes nuevas y las tarifas de cada solicitud quedan guardadas en la base.
# Fuentes: deepgram.com/pricing, ai.google.dev/gemini-api/docs/pricing,
# api-docs.deepseek.com/quick_start/pricing, console.groq.com/docs/models
# y developers.openai.com/api/docs/pricing (23-09-2026).
# La tarifa por minuto de transcribe-diarize aproxima el costo de gpt-4o-transcribe;
# el modelo de diarización publica precios por tokens y el formato diarized_json
# puede no devolver los contadores necesarios para calcularlos con exactitud.
DEFAULT_PRICES = {
    ("transcription", "deepgram", "nova-3"): ("minute", 0.0043, 0.0, 0.0),
    ("transcription", "openai", "gpt-4o-transcribe-diarize"): ("minute", 0.006, 0.0, 0.0),
    ("transcription", "openai", "gpt-4o-transcribe"): ("minute", 0.006, 0.0, 0.0),
    ("transcription", "openai", "gpt-4o-mini-transcribe"): ("minute", 0.003, 0.0, 0.0),
    ("analysis", "gemini", "gemini-3.5-flash"): ("million_tokens", 1.50, 9.0, 0.15),
    ("analysis", "deepseek", "deepseek-flash"): ("million_tokens", 0.30, 1.20, 0.006),
    ("analysis", "groq", "openai/gpt-oss-120b"): ("million_tokens", 0.15, 0.60, 0.075),
    ("analysis", "openai", "gpt-4o-mini"): ("million_tokens", 0.15, 0.60, 0.075),
}
DEEPGRAM_KEYTERM_RATE = 0.0013  # USD/min, audio pregrabado con Keyterm Prompting.


def price_for_request(service: str, provider: str, model: str, payload: dict,
                      *, keyterm: bool = False):
    """Devuelve la tarifa publicada aplicable a esta solicitud, si existe."""
    price = DEFAULT_PRICES.get((service, provider, model))
    if price is None:
        return None
    unit, input_rate, output_rate, cached_input_rate = price
    if (service, provider, model) == ('transcription', 'deepgram', 'nova-3') and keyterm:
        input_rate += DEEPGRAM_KEYTERM_RATE
    if (service, provider, model) == ('analysis', 'deepseek', 'deepseek-flash'):
        try:
            created = datetime.fromtimestamp(int(payload['created']), timezone.utc)
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            created = datetime.now(timezone.utc)
        peak = created.weekday() < 5 and (1 <= created.hour < 4 or 6 <= created.hour < 10)
        if not peak:
            input_rate /= 2
            output_rate /= 2
            cached_input_rate /= 2
    return unit, input_rate, output_rate, cached_input_rate


def usage_from_response(service: str, provider: str, payload: dict, fallback_seconds: float | None):
    """Extrae solo contadores de facturación; nunca texto ni credenciales."""
    if service == "transcription":
        metadata = payload.get("metadata") or {}
        usage = payload.get("usage") or {}
        seconds = metadata.get("duration") if provider == "deepgram" else (
            usage.get("seconds") or payload.get("duration"))
        if seconds is None:
            seconds = fallback_seconds
        return (_number(seconds), _integer(usage.get("input_tokens")),
                _integer(usage.get("output_tokens")), 0)
    usage = payload.get("usageMetadata") if provider == "gemini" else payload.get("usage")
    usage = usage or {}
    input_tokens = usage.get("promptTokenCount") if provider == "gemini" else usage.get("prompt_tokens")
    output_tokens = usage.get("candidatesTokenCount") if provider == "gemini" else usage.get("completion_tokens")
    if provider == "gemini":
        cached_input = usage.get("cachedContentTokenCount", 0)
    else:
        details = usage.get("prompt_tokens_details") or {}
        cached_input = (usage.get("prompt_cache_hit_tokens") or details.get("cached_tokens", 0))
    if provider == "gemini" and output_tokens is not None:
        # Los tokens de pensamiento están incluidos en la facturación de salida.
        output_tokens = int(output_tokens) + int(usage.get("thoughtsTokenCount") or 0)
    return None, _integer(input_tokens), _integer(output_tokens), _integer(cached_input)


def _number(value):
    try:
        result = float(value)
        return result if 0 <= result < 1e12 else None
    except (TypeError, ValueError):
        return None


def _integer(value):
    number = _number(value)
    return int(number) if number is not None else None


def estimated_cost(unit: str, input_rate: float, output_rate: float,
                   seconds: float | None, input_tokens: int | None, output_tokens: int | None,
                   cached_input_rate: float = 0.0, cached_input_tokens: int = 0):
    if unit == "minute":
        return (seconds / 60 * input_rate) if seconds is not None else None
    if unit == "million_tokens" and input_tokens is not None and output_tokens is not None:
        cached = min(input_tokens, max(0, cached_input_tokens))
        return ((input_tokens-cached) * input_rate + cached * cached_input_rate +
                output_tokens * output_rate) / 1_000_000
    return None


def load_cost_report(database, start: date, end: date, service: str = '', provider: str = ''):
    with database.connect() as connection:
        events = [dict(row) for row in connection.execute("""
            SELECT u.id, u.call_id, u.created_at, u.service, u.provider, u.model, u.request_id,
                   u.audio_seconds, u.input_tokens, u.output_tokens, u.cached_input_tokens,
                   u.cost_usd, u.price_unit, u.input_rate, u.cached_input_rate, u.output_rate,
                   c.filename, datetime(u.created_at,'localtime') AS local_at
            FROM api_usage u LEFT JOIN calls c ON c.id=u.call_id
            WHERE date(u.created_at,'localtime')>=? AND date(u.created_at,'localtime')<?
              AND (?='' OR u.service=?) AND (?='' OR u.provider=?)
            ORDER BY u.created_at DESC, u.id DESC
        """, (start.isoformat(), end.isoformat(), service, service, provider, provider))]
    daily = []
    daily_by_date = {}
    day = start
    while day < end:
        row = {"date": day.isoformat(), "label": day.strftime('%d/%m'),
               "transcription_usd": 0.0, "analysis_usd": 0.0, "total_usd": 0.0,
               "transcription_requests": 0, "analysis_requests": 0,
               "unpriced": 0, "models": {}}
        daily.append(row)
        daily_by_date[row['date']] = row
        day += timedelta(days=1)
    grouped = {}
    by_call = {}
    for event in events:
        daily_row = daily_by_date[event['local_at'][:10]]
        daily_row[f"{event['service']}_requests"] += 1
        daily_row[f"{event['service']}_usd"] += event['cost_usd'] or 0
        daily_row['total_usd'] += event['cost_usd'] or 0
        daily_row['unpriced'] += event['cost_usd'] is None
        key = (event['service'], event['provider'], event['model'])
        model_row = daily_row['models'].setdefault(key, {"service": key[0], "provider": key[1],
                                                   "model": key[2], "requests": 0,
                                                   "cost_usd": 0.0, "unpriced": 0})
        model_row['requests'] += 1
        model_row['cost_usd'] += event['cost_usd'] or 0
        model_row['unpriced'] += event['cost_usd'] is None
        entry = grouped.setdefault(key, {"service": key[0], "provider": key[1], "model": key[2],
                                         "requests": 0, "cost_usd": 0.0, "unpriced": 0})
        entry['requests'] += 1
        entry['cost_usd'] += event['cost_usd'] or 0
        entry['unpriced'] += event['cost_usd'] is None
        call_key = event['call_id'] if event['call_id'] is not None else f"deleted-{event['id']}"
        call_entry = by_call.setdefault(call_key, {"filename": event['filename'] or 'Llamada eliminada',
                                                   "requests": 0, "cost_usd": 0.0, "unpriced": 0})
        call_entry['requests'] += 1
        call_entry['cost_usd'] += event['cost_usd'] or 0
        call_entry['unpriced'] += event['cost_usd'] is None
    for row in daily:
        row['models'] = sorted(row['models'].values(),
                               key=lambda item: (-item['cost_usd'], item['service'], item['model']))
    return {"events": events, "daily": daily, "by_model": list(grouped.values()),
            "by_call": list(by_call.values()),
            "requests": len(events), "unpriced": sum(e['cost_usd'] is None for e in events),
            "total_usd": sum(e['cost_usd'] or 0 for e in events),
            "transcription_usd": sum((e['cost_usd'] or 0) for e in events if e['service'] == 'transcription'),
            "analysis_usd": sum((e['cost_usd'] or 0) for e in events if e['service'] == 'analysis')}
