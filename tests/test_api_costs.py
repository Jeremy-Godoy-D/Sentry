"""Facturación local: una solicitud real se cuenta una vez aun con caché."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import openpyxl

from app.database import Database
from app.services import audio_analysis
from app.services.api_cost_export import export_api_costs_excel
from app.services.api_costs import load_cost_report


class ApiCostsTests(unittest.TestCase):
    def test_automatic_tariffs_and_excel_totals(self):
        with TemporaryDirectory() as folder:
            database = Database(Path(folder) / 'costs.db')
            path = Path(folder) / 'audio.wav'
            database.record_api_usage(path, 'transcription', 'deepgram', 'nova-3',
                                      {'metadata': {'duration': 60, 'request_id': 'dg-1'}}, 60,
                                      keyterm=True)
            database.record_api_usage(path, 'analysis', 'gemini', 'gemini-3.5-flash',
                                      {'usageMetadata': {'promptTokenCount': 1000,
                                                         'candidatesTokenCount': 100}}, None)
            for hour in (2, 12):
                created = datetime(2026, 9, 21, hour, tzinfo=timezone.utc)
                database.record_api_usage(path, 'analysis', 'deepseek', 'deepseek-flash',
                                          {'created': int(created.timestamp()),
                                           'usage': {'prompt_tokens': 1000, 'completion_tokens': 100}}, None)
            with database.connect() as connection:
                connection.execute("UPDATE api_usage SET created_at='2026-09-23 12:00:00'")
            start, end = date(2026, 9, 23), date(2026, 9, 24)
            report = load_cost_report(database, start, end)
            self.assertAlmostEqual(report['total_usd'], 0.00863)
            output = export_api_costs_excel(database, Path(folder) / 'gastos.xlsx', start, end)
            book = openpyxl.load_workbook(output, data_only=True)
            try:
                self.assertEqual(book.sheetnames, ['Resumen', 'Diario', 'Solicitudes', 'Tarifas'])
                self.assertAlmostEqual(book['Resumen']['B12'].value, report['total_usd'])
                self.assertAlmostEqual(book['Solicitudes']['P6'].value, report['total_usd'])
                self.assertAlmostEqual(book['Tarifas']['I19'].value, report['total_usd'])
                self.assertEqual(book['Solicitudes'].max_row, 6)
            finally:
                book.close()

    def test_request_cache_and_historical_rate(self):
        with TemporaryDirectory() as folder:
            database = Database(Path(folder) / 'costs.db')
            path = Path(folder) / 'audio.wav'
            with database.connect() as connection:
                connection.execute('INSERT INTO calls(filename,file_path,duration_seconds) VALUES (?,?,?)',
                                   (path.name, str(path), 60))
            response = SimpleNamespace(status_code=200, headers={}, json=lambda: {
                'metadata': {'duration': 60, 'request_id': 'provider-request-1'}, 'results': {}})
            session = Mock(request=Mock(return_value=response))
            context = audio_analysis._COST_CONTEXT.set({
                'database': database, 'path': path, 'duration_seconds': 60,
                'config': {'transcription_model': 'nova-3'},
            })
            try:
                with patch.object(audio_analysis._HTTP, 'session', session, create=True):
                    compute = lambda: audio_analysis._request('POST', 'https://api.deepgram.com/v1/listen')
                    first, cached_first = audio_analysis._cached_computation(database, 'transcription_cache', 'audio-1', compute)
                    second, cached_second = audio_analysis._cached_computation(database, 'transcription_cache', 'audio-1', compute)
            finally:
                audio_analysis._COST_CONTEXT.reset(context)
            self.assertEqual(first, second)
            self.assertFalse(cached_first)
            self.assertTrue(cached_second)
            session.request.assert_called_once()
            today = date.today()
            report = load_cost_report(database, today, today + timedelta(days=1))
            self.assertEqual(report['requests'], 1)
            self.assertAlmostEqual(report['total_usd'], .0043)
            database.save_api_price('transcription', 'deepgram', 'nova-3', 'minute', .01, 0)
            self.assertAlmostEqual(load_cost_report(database, today, today + timedelta(days=1))['total_usd'], .0043)
            database.record_api_usage(path, 'transcription', 'deepgram', 'nova-3',
                                      {'metadata': {'duration': 60, 'request_id': 'provider-request-2'}}, 60)
            self.assertAlmostEqual(load_cost_report(database, today, today + timedelta(days=1))['total_usd'], .0086)

    def test_missing_rate_keeps_usage_visible_without_inventing_cost(self):
        with TemporaryDirectory() as folder:
            database = Database(Path(folder) / 'costs.db')
            database.record_api_usage(Path(folder) / 'audio.wav', 'analysis', 'gemini', 'custom-model',
                                      {'usageMetadata': {'promptTokenCount': 500, 'candidatesTokenCount': 30}}, None)
            today = date.today()
            report = load_cost_report(database, today, today + timedelta(days=1))
            self.assertEqual(report['requests'], 1)
            self.assertEqual(report['unpriced'], 1)
            self.assertIsNone(report['events'][0]['cost_usd'])

    def test_daily_chart_breaks_down_both_services_and_models(self):
        with TemporaryDirectory() as folder:
            database = Database(Path(folder) / 'costs.db')
            path = Path(folder) / 'audio.wav'
            database.record_api_usage(path, 'transcription', 'deepgram', 'nova-3',
                                      {'metadata': {'duration': 60}}, 60)
            database.record_api_usage(path, 'analysis', 'gemini', 'gemini-3.5-flash-lite',
                                      {'usageMetadata': {'promptTokenCount': 1000,
                                                         'candidatesTokenCount': 100}}, None)
            with database.connect() as connection:
                connection.execute("UPDATE api_usage SET created_at=datetime('2026-09-21 12:00:00','utc')")
            report = load_cost_report(database, date(2026, 9, 21), date(2026, 9, 24))
            self.assertEqual(len(report['daily']), 3)
            day = report['daily'][0]
            self.assertEqual(day['date'], '2026-09-21')
            self.assertEqual(day['transcription_requests'], 1)
            self.assertEqual(day['analysis_requests'], 1)
            self.assertAlmostEqual(day['transcription_usd'], .0043)
            self.assertAlmostEqual(day['total_usd'],
                                   day['transcription_usd'] + day['analysis_usd'])
            self.assertEqual({row['model'] for row in day['models']},
                             {'nova-3', 'gemini-3.5-flash-lite'})
            self.assertEqual(report['daily'][1]['total_usd'], 0)


if __name__ == '__main__':
    unittest.main()
