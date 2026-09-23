"""Pantalla de consumo y costo estimado de las APIs."""
from __future__ import annotations

from datetime import date, timedelta
import html
from pathlib import Path
import sqlite3

from PySide6.QtCore import QDate, Qt, QThread, Signal, QRectF
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QComboBox, QDateEdit, QFileDialog,
    QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QScrollArea, QTabWidget, QTableWidgetItem, QToolTip,
    QVBoxLayout, QWidget)

from app.services.analytics import period_bounds
from app.services.api_cost_export import export_api_costs_excel
from app.services.api_costs import RECOMMENDED_API_MODELS, load_cost_report
from app.ui.theme import theme_colors
from app.ui.views.reports_page import ReportsPage


def money(value: float) -> str:
    return f'${value:,.6f}'


class CostWorker(QThread):
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, database, start, end, service, provider, parent):
        super().__init__(parent)
        self.database = database
        self.start_date, self.end_date = start, end
        self.service, self.provider = service, provider

    def run(self):
        try:
            self.ready.emit(load_cost_report(self.database, self.start_date, self.end_date,
                                             self.service, self.provider))
        except (sqlite3.Error, OSError, ValueError) as exc:
            self.failed.emit(str(exc))


class CostExportWorker(QThread):
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, database, output, start, end, service, provider, parent):
        super().__init__(parent)
        self.database, self.output = database, Path(output)
        self.start_date, self.end_date = start, end
        self.service, self.provider = service, provider

    def run(self):
        try:
            path = export_api_costs_excel(self.database, self.output, self.start_date,
                                          self.end_date, self.service, self.provider)
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(str(path))


class CostChart(QWidget):
    TRANSCRIPTION_COLOR = '#27953c'
    ANALYSIS_COLOR = '#4f79cf'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.hovered_index = None
        self.setMinimumHeight(175)
        self.setMouseTracking(True)
        self.setAccessibleName('Gasto estimado diario en dólares')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = theme_colors(self.window().theme)
        maximum = max((row['total_usd'] for row in self.rows), default=0) or 1
        width = (self.width() - 30) / max(1, len(self.rows))
        baseline = self.height() - 30
        plot_height = max(1, baseline - 32)
        for index, row in enumerate(self.rows):
            x = 15 + index * width
            if index == self.hovered_index:
                painter.fillRect(QRectF(x, 0, width, baseline + 5), QColor(colors['surface_hover']))
            bar_width = min(34, width * .62)
            transcription_height = plot_height * row['transcription_usd'] / maximum
            analysis_height = plot_height * row['analysis_usd'] / maximum
            # Mantiene visibles los importes pequeños sin alterar los datos del tooltip.
            if transcription_height:
                transcription_height = max(2.5, transcription_height)
            if analysis_height:
                analysis_height = max(2.5, analysis_height)
            combined = transcription_height + analysis_height
            if combined > plot_height:
                transcription_height *= plot_height / combined
                analysis_height *= plot_height / combined
            bar_x = x + (width-bar_width)/2
            if transcription_height:
                painter.fillRect(QRectF(bar_x, baseline-transcription_height,
                                        bar_width, transcription_height), QColor(self.TRANSCRIPTION_COLOR))
            if analysis_height:
                painter.fillRect(QRectF(bar_x, baseline-transcription_height-analysis_height,
                                        bar_width, analysis_height), QColor(self.ANALYSIS_COLOR))
            painter.setPen(QColor(colors['text']))
            if len(self.rows) <= 7:
                painter.drawText(QRectF(x, 0, width, 20), Qt.AlignmentFlag.AlignCenter,
                                 money(row['total_usd']) if row['total_usd'] else '—')
            painter.setPen(QColor(colors['muted']))
            if len(self.rows) <= 7 or index % 5 == 0 or index == len(self.rows)-1:
                painter.drawText(QRectF(x-8, baseline+5, width+16, 22),
                                 Qt.AlignmentFlag.AlignCenter, row['label'])
        painter.end()

    @staticmethod
    def tooltip_for_day(row):
        requests = row['transcription_requests'] + row['analysis_requests']
        lines = [f"<b>{html.escape(row['date'])}</b>",
                 f"Total estimado: <b>{money(row['total_usd'])}</b> · {requests} solicitudes",
                 f"<span style='color:{CostChart.TRANSCRIPTION_COLOR}'>■</span> "
                 f"Transcripción: {money(row['transcription_usd'])} · {row['transcription_requests']} solicitudes",
                 f"<span style='color:{CostChart.ANALYSIS_COLOR}'>■</span> "
                 f"Análisis: {money(row['analysis_usd'])} · {row['analysis_requests']} solicitudes"]
        if row['unpriced']:
            lines.append(f"Sin estimación: {row['unpriced']} solicitudes")
        if row['models']:
            lines.append('<hr><b>Por modelo</b>')
            for model in row['models']:
                name = html.escape(f"{model['provider']} · {model['model']}")
                detail = f"{money(model['cost_usd'])} · {model['requests']} solicitudes"
                if model['unpriced']:
                    detail += f" · {model['unpriced']} sin estimación"
                lines.append(f"{name}: {detail}")
        return '<br>'.join(lines)

    def mouseMoveEvent(self, event):
        width = (self.width() - 30) / max(1, len(self.rows))
        index = int((event.position().x() - 15) / width) if width else -1
        if event.position().x() < 15 or index >= len(self.rows):
            index = -1
        if index != self.hovered_index:
            self.hovered_index = index if index >= 0 else None
            if self.hovered_index is None:
                QToolTip.hideText()
            else:
                QToolTip.showText(event.globalPosition().toPoint(),
                                  self.tooltip_for_day(self.rows[index]), self)
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.hovered_index = None
        QToolTip.hideText()
        self.update()
        super().leaveEvent(event)


class ApiCostsPage(QScrollArea):
    PROVIDER_LABELS = {'deepgram': 'Deepgram', 'gemini': 'Gemini', 'deepseek': 'DeepSeek',
                       'groq': 'Groq',
                       'openai': 'OpenAI'}

    def __init__(self, database, parent=None):
        super().__init__(parent)
        self.setObjectName('apiCostsPage')
        self.database, self.worker, self.export_worker, self.result = database, None, None, None
        with database.connect() as connection:
            self.observed_providers = {(row['service'], row['provider']) for row in connection.execute(
                'SELECT DISTINCT service,provider FROM api_usage')}
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        self.setWidget(content)
        outer = QVBoxLayout(content)
        outer.setContentsMargins(28, 24, 28, 28)
        outer.setSpacing(18)
        header = QHBoxLayout()
        title = QLabel('Costes de API')
        title.setObjectName('pageTitle')
        header.addWidget(title)
        header.addStretch()
        outer.addLayout(header)
        subtitle = QLabel('Gasto estimado en USD: Deepgram Nova-3 para transcripción; '
                          'Gemini 3.5 Flash, DeepSeek V4.1 Flash o Groq GPT-OSS 120B para análisis.')
        subtitle.setObjectName('pageSubtitle')
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)
        toolbar = QFrame()
        toolbar.setObjectName('reportToolbar')
        controls = QHBoxLayout(toolbar)
        controls.setContentsMargins(16, 12, 16, 12)
        controls.setSpacing(12)
        self.period = QComboBox()
        for label, key in (('1 día', 'day'), ('1 semana', 'week'), ('1 mes', 'month'),
                           ('Todo el historial', 'all')):
            self.period.addItem(label, key)
        self.period.setCurrentIndex(2)
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat('dd/MM/yyyy')
        self.service = QComboBox()
        for label, key in (('Todos', ''), ('Transcripción', 'transcription'), ('Análisis', 'analysis')):
            self.service.addItem(label, key)
        self.provider = QComboBox()
        self._update_provider_options()
        self.refresh_button = QPushButton('Actualizar')
        self.refresh_button.setObjectName('secondaryButton')
        for label, control in (('Período', self.period), ('Fecha de referencia', self.date),
                               ('Servicio', self.service), ('Proveedor', self.provider)):
            group = QVBoxLayout()
            group.setSpacing(5)
            caption = QLabel(label)
            caption.setObjectName('fieldLabel')
            group.addWidget(caption)
            group.addWidget(control)
            controls.addLayout(group)
        controls.addStretch()
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(self.refresh_button)
        self.export_button = QPushButton('Exportar Excel')
        self.export_button.setObjectName('validateButton')
        self.export_button.setToolTip('Exportar solicitudes, totales y tarifas del período y filtros elegidos')
        actions.addWidget(self.export_button)
        controls.addLayout(actions)
        controls.setAlignment(actions, Qt.AlignmentFlag.AlignBottom)
        outer.addWidget(toolbar)
        self.range_label = QLabel()
        self.range_label.setObjectName('pageSubtitle')
        outer.addWidget(self.range_label)
        self.export_status = QLabel('')
        self.export_status.setObjectName('apiStatus')
        self.export_status.setWordWrap(True)
        outer.addWidget(self.export_status)
        self.metrics = {}
        cards = QGridLayout()
        for index, (key, caption) in enumerate((('total_usd', 'Total estimado'),
                ('transcription_usd', 'Transcripción'), ('analysis_usd', 'Análisis'),
                ('requests', 'Solicitudes reales'))):
            card = QFrame()
            card.setObjectName('reportMetric')
            box = QVBoxLayout(card)
            box.setContentsMargins(18, 14, 18, 14)
            value = QLabel('—')
            value.setObjectName('reportValueAccent' if key == 'total_usd' else 'reportValue')
            box.addWidget(value)
            label = QLabel(caption)
            label.setObjectName('reportLabel')
            box.addWidget(label)
            self.metrics[key] = value
            cards.addWidget(card, 0, index)
        outer.addLayout(cards)
        self.summary = QLabel('')
        self.summary.setObjectName('pageSubtitle')
        self.summary.setWordWrap(True)
        outer.addWidget(self.summary)
        panel = QFrame()
        panel.setObjectName('reportSection')
        panel_layout = QVBoxLayout(panel)
        chart_heading = QHBoxLayout()
        chart_title = QLabel('Gasto diario estimado')
        chart_title.setObjectName('formTitle')
        chart_heading.addWidget(chart_title)
        chart_heading.addStretch()
        transcription_legend = QLabel('■ Transcripción')
        transcription_legend.setStyleSheet(f'color: {CostChart.TRANSCRIPTION_COLOR}; font-weight: 600;')
        chart_heading.addWidget(transcription_legend)
        analysis_legend = QLabel('■ Análisis')
        analysis_legend.setStyleSheet(f'color: {CostChart.ANALYSIS_COLOR}; font-weight: 600;')
        chart_heading.addWidget(analysis_legend)
        panel_layout.addLayout(chart_heading)
        chart_hint = QLabel('Cada barra representa un día. Pasa el cursor para ver costos, solicitudes y modelos.')
        chart_hint.setObjectName('pageSubtitle')
        panel_layout.addWidget(chart_hint)
        self.chart = CostChart()
        self.chart_scroll = QScrollArea()
        self.chart_scroll.setObjectName('costChartScroll')
        self.chart_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.chart_scroll.setWidgetResizable(True)
        self.chart_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.chart_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chart_scroll.setFixedHeight(205)
        self.chart_scroll.setWidget(self.chart)
        panel_layout.addWidget(self.chart_scroll)
        outer.addWidget(panel)
        section = QFrame()
        section.setObjectName('reportSection')
        section_layout = QVBoxLayout(section)
        section_layout.addWidget(QLabel('Desglose del período'))
        self.tabs = QTabWidget()
        self.tabs.setObjectName('reportTabs')
        self.models = ReportsPage.table(['Servicio', 'Proveedor', 'Modelo', 'Solicitudes', 'Costo USD', 'Sin estimación'], 220, 2)
        self.calls = ReportsPage.table(['Grabación', 'Solicitudes', 'Costo USD', 'Sin estimación'], 260, 0)
        self.events = ReportsPage.table(['Fecha', 'Servicio', 'Proveedor', 'Modelo', 'Grabación', 'Consumo', 'Costo USD'], 300, 4)
        self.tabs.addTab(self.models, 'Por modelo')
        self.tabs.addTab(self.calls, 'Por llamada')
        self.tabs.addTab(self.events, 'Solicitudes')
        section_layout.addWidget(self.tabs)
        outer.addWidget(section)
        note = QLabel('Sentry calcula automáticamente el importe de cada solicitud usando su consumo y la tarifa de referencia vigente en la aplicación. '
                      'Deepgram añade el precio de Keyterm cuando se envían términos; DeepSeek aplica sus franjas pico y fuera de pico en UTC. '
                      'Las respuestas reutilizadas desde caché no generan otra solicitud. Los importes son estimados y pueden diferir de la '
                      'factura por planes, créditos, impuestos o cambios de tarifa; en el plan gratis de Groq '
                      'puede no existir un cargo real. “Sin estimación” indica un dato de uso o tarifa faltante.')
        note.setObjectName('pageSubtitle')
        note.setWordWrap(True)
        outer.addWidget(note)
        outer.addStretch()
        for control in (self.period, self.date, self.provider):
            signal = control.dateChanged if control is self.date else control.currentIndexChanged
            signal.connect(self.refresh)
        self.service.currentIndexChanged.connect(self._service_changed)
        self.refresh_button.clicked.connect(self.refresh)
        self.export_button.clicked.connect(self.export_excel)

    def _update_provider_options(self):
        service_filter = self.service.currentData()
        selected = self.provider.currentData()
        current = [(service, provider) for service, providers in RECOMMENDED_API_MODELS.items()
                   for provider in providers if not service_filter or service == service_filter]
        legacy = sorted((service, provider) for service, provider in self.observed_providers
                        if (not service_filter or service == service_filter) and
                        (service, provider) not in current)
        self.provider.blockSignals(True)
        self.provider.clear()
        self.provider.addItem('Todos', '')
        added = set()
        for _service, provider in current + legacy:
            if provider in added:
                continue
            label = self.PROVIDER_LABELS.get(provider, provider.title())
            self.provider.addItem(label + (' (histórico)' if (_service, provider) in legacy else ''), provider)
            added.add(provider)
        self.provider.setCurrentIndex(max(0, self.provider.findData(selected)))
        self.provider.blockSignals(False)

    def _service_changed(self):
        self._update_provider_options()
        self.refresh()

    def _selected_bounds(self):
        reference = self.date.date().toPython()
        if self.period.currentData() != 'all':
            return period_bounds(reference, self.period.currentData())
        with self.database.connect() as connection:
            bounds = connection.execute(
                "SELECT MIN(date(created_at,'localtime')), MAX(date(created_at,'localtime')) FROM api_usage"
            ).fetchone()
        first = date.fromisoformat(bounds[0]) if bounds[0] else reference
        last = date.fromisoformat(bounds[1]) if bounds[1] else reference
        return first, max(last, reference) + timedelta(days=1)

    def refresh(self):
        if self.worker is not None or self.export_worker is not None:
            return
        start, end = self._selected_bounds()
        self.range_label.setText(f'{start:%d/%m/%Y} — {end-timedelta(days=1):%d/%m/%Y} · Fechas en hora local')
        self.summary.setText('Cargando consumo…')
        for control in (self.period, self.date, self.service, self.provider,
                        self.refresh_button, self.export_button):
            control.setEnabled(False)
        self.worker = CostWorker(self.database, start, end, self.service.currentData(),
                                 self.provider.currentData(), self)
        self.worker.ready.connect(self.render)
        self.worker.failed.connect(self.failed)
        self.worker.finished.connect(self.finished)
        self.worker.start()

    def finished(self):
        self.worker.deleteLater()
        self.worker = None
        for control in (self.period, self.service, self.provider, self.refresh_button):
            control.setEnabled(True)
        self.date.setEnabled(self.period.currentData() != 'all')
        self.export_button.setEnabled(self.export_worker is None)

    def export_excel(self):
        if self.export_worker is not None or self.worker is not None:
            return
        start, end = self._selected_bounds()
        suggested = f'Sentry_Costes_API_{start:%Y%m%d}_{end-timedelta(days=1):%Y%m%d}.xlsx'
        path, _ = QFileDialog.getSaveFileName(self, 'Exportar costes de API', suggested,
                                               'Excel (*.xlsx)')
        if not path:
            return
        for control in (self.period, self.date, self.service, self.provider, self.refresh_button):
            control.setEnabled(False)
        self.export_button.setEnabled(False)
        self.export_button.setText('Exportando…')
        self.export_status.setText('Preparando el Excel con todas las solicitudes del período…')
        self.export_worker = CostExportWorker(self.database, path, start, end,
                                              self.service.currentData(), self.provider.currentData(), self)
        self.export_worker.succeeded.connect(self._export_succeeded)
        self.export_worker.failed.connect(self._export_failed)
        self.export_worker.finished.connect(self._export_finished)
        self.export_worker.start()

    def _export_succeeded(self, path):
        self.export_status.setText(f'Excel guardado: {path}')
        self.export_status.setToolTip(path)

    def _export_failed(self, message):
        self.export_status.setText(f'No se pudo exportar el Excel: {message}')
        QMessageBox.warning(self, 'Exportación fallida', message)

    def _export_finished(self):
        self.export_worker.deleteLater()
        self.export_worker = None
        for control in (self.period, self.service, self.provider, self.refresh_button):
            control.setEnabled(True)
        self.date.setEnabled(self.period.currentData() != 'all')
        self.export_button.setText('Exportar Excel')
        self.export_button.setEnabled(self.worker is None)

    def failed(self, message):
        self.result = None
        for value in self.metrics.values():
            value.setText('—')
        self.models.setRowCount(0)
        self.calls.setRowCount(0)
        self.events.setRowCount(0)
        self.chart.rows = []
        self.chart.hovered_index = None
        QToolTip.hideText()
        self.chart.update()
        self.summary.setText(f'No se pudo cargar el consumo: {message}')

    def render(self, result):
        self.result = result
        for key, value in self.metrics.items():
            value.setText(str(result[key]) if key == 'requests' else money(result[key]))
        self.summary.setText(
            f"{result['unpriced']} solicitudes sin estimación por datos de uso o tarifas faltantes."
            if result['unpriced'] else
            f"{result['requests']} solicitudes registradas en el período."
            if result['requests'] else
            'Aún no hay solicitudes registradas en este período.'
        )
        self.chart.rows = result['daily']
        self.chart.setMinimumWidth(max(500, len(result['daily']) * 28))
        self.chart.hovered_index = None
        QToolTip.hideText()
        self.chart.setAccessibleDescription('; '.join(
            f"{row['date']}: transcripción {money(row['transcription_usd'])} en "
            f"{row['transcription_requests']} solicitudes, análisis {money(row['analysis_usd'])} "
            f"en {row['analysis_requests']} solicitudes"
            for row in result['daily']))
        self.chart.update()
        groups = [(item['service'], item['provider'], item['model'], item['requests'],
                   money(item['cost_usd']), item['unpriced']) for item in result['by_model']]
        calls = [(item['filename'], item['requests'], money(item['cost_usd']), item['unpriced'])
                 for item in result['by_call']]
        events = []
        for item in result['events']:
            consumption = (f"{item['audio_seconds']:.1f} s" if item['audio_seconds'] is not None else
                           f"{item['input_tokens'] or 0} ent. ({item['cached_input_tokens'] or 0} en caché) / "
                           f"{item['output_tokens'] or 0} sal." if
                           item['input_tokens'] is not None or item['output_tokens'] is not None else 'Sin datos')
            events.append((item['local_at'], item['service'], item['provider'], item['model'],
                           item['filename'] or '—', consumption,
                           money(item['cost_usd']) if item['cost_usd'] is not None else 'Sin estimación'))
        for table, rows in ((self.models, groups), (self.calls, calls[:500]), (self.events, events[:500])):
            table.setSortingEnabled(False)
            table.setRowCount(len(rows))
            for index, row in enumerate(rows):
                for column, value in enumerate(row):
                    item = QTableWidgetItem(str(value))
                    item.setToolTip(' · '.join(str(part) for part in row))
                    table.setItem(index, column, item)
            table.setSortingEnabled(True)
