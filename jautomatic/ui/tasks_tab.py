"""Real, manually recorded paid work with a separate task workflow."""
from dataclasses import replace
from html import escape
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QDialog,
    QDialogButtonBox, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox,
    QPlainTextEdit, QTableWidget, QTableWidgetItem, QHeaderView, QTextBrowser, QInputDialog)
from ..services.paid_tasks import PaidTask, TaskStore, STAGES, CATEGORIES, UNITS, ELIGIBILITY, matches_filters
from ..services.task_platforms import task_platform, task_platform_names, task_search_terms
from ..services.task_recommendations import recommended_task_sources
from . import theme as th


def combo(values):
    widget = QComboBox()
    widget.addItems(values)
    return widget


class TaskDialog(QDialog):
    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.task = task
        self.setWindowTitle('Task details from your platform')
        self.resize(540, 600)
        layout = QVBoxLayout(self)
        layout.addWidget(th.label('Copy the details shown in Clickworker or another platform. Availability and eligibility are not checked automatically.', 'muted', wrap=True))
        form = QFormLayout()
        self.title = QLineEdit(task.title)
        self.platform = QLineEdit(task.platform)
        self.url = QLineEdit(task.url)
        self.category = combo(CATEGORIES); self.category.setCurrentText(task.category)
        self.amount = QDoubleSpinBox(); self.amount.setRange(0, 1000000); self.amount.setValue(task.amount or 0)
        self.unknown = QCheckBox('Pay not shown'); self.unknown.setChecked(task.amount is None)
        self.amount.setEnabled(task.amount is not None)
        self.unknown.toggled.connect(lambda value: self.amount.setEnabled(not value))
        self.currency = QLineEdit(task.currency); self.currency.setMaxLength(3)
        self.unit = combo(UNITS); self.unit.setCurrentText(task.unit)
        self.minutes = QSpinBox(); self.minutes.setRange(0, 100000); self.minutes.setSpecialValueText('Unknown'); self.minutes.setValue(task.minutes)
        self.deadline = QLineEdit(task.deadline); self.deadline.setPlaceholderText('YYYY-MM-DD, or leave blank')
        self.eligibility = combo(ELIGIBILITY); self.eligibility.setCurrentText(task.eligibility)
        self.notes = QPlainTextEdit(task.description); self.notes.setMaximumHeight(100)
        for label, field in [('Title',self.title),('Platform',self.platform),('Task link',self.url),('Task type',self.category),('Advertised pay',self.amount),('',self.unknown),('Currency',self.currency),('Pay per',self.unit),('Estimated minutes',self.minutes),('Deadline',self.deadline),('Eligibility',self.eligibility),('Requirements / notes',self.notes)]: form.addRow(label, field)
        layout.addLayout(form)
        self.error = th.label('', 'muted', wrap=True); layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def value(self):
        return replace(self.task, title=self.title.text(), platform=self.platform.text(), url=self.url.text(),
            category=self.category.currentText(), amount=None if self.unknown.isChecked() else self.amount.value(),
            currency=self.currency.text().strip().upper(), unit=self.unit.currentText(), minutes=self.minutes.value(),
            deadline=self.deadline.text().strip(), eligibility=self.eligibility.currentText(), description=self.notes.toPlainText())


class TasksTab(QWidget):
    page_title = 'Tasks'
    page_subtitle = 'Choose paid work, track progress and record payments'

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.store = TaskStore(ctx.workspace)
        self.checked = set()
        self.platform_boxes = {}
        layout = QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        sources = th.Card('Find work on task websites', 'Search opens the checked websites in your browser with your words. Sign in there, then record real task details with Add task details. No live account sync is connected.')
        search_row = QHBoxLayout()
        self.query = QLineEdit(ctx.settings.task_search_query)
        self.query.setPlaceholderText('Search words — e.g. data entry, web research, testing')
        self.query.setToolTip('Filters the recorded tasks below as you type. The Search tasks button also opens the checked websites with these words.')
        self.query.returnPressed.connect(self.search_websites)
        search_row.addWidget(self.query, 1)
        self.search_button = th.button('Search tasks', 'primary', 'Open every checked website in your browser with these search words', self.search_websites)
        search_row.addWidget(self.search_button)
        sources.add_layout(search_row)
        sites = QGridLayout()
        enabled = set(ctx.settings.task_platforms_enabled)
        for index, name in enumerate(task_platform_names()):
            platform = task_platform(name)
            box = QCheckBox(platform.label)
            box.setChecked(name in enabled)
            box.setToolTip(platform.hint + ('\n' + platform.homepage if platform.homepage else ''))
            box.toggled.connect(self.platforms_changed)
            self.platform_boxes[name] = box
            sites.addWidget(box, index // 4, index % 4)
        sources.add_layout(sites)
        self.web_status = th.label('Tick the websites to search. Each one opens in your browser; availability and eligibility stay on the platform.', 'small', wrap=True)
        sources.add(self.web_status)
        actions = QHBoxLayout()
        actions.addWidget(th.button('Add task details', 'default', 'Add a real opportunity for review; it will not enter My tasks automatically', self.add_task))
        actions.addStretch(1); sources.add_layout(actions)
        self.recommendations = QTextBrowser(); self.recommendations.setOpenExternalLinks(True)
        self.recommendations.setMaximumHeight(52); self.recommendations.setFrameShape(QTextBrowser.NoFrame)
        self.recommendations.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sources.add(self.recommendations)
        layout.addWidget(sources)
        filters = QHBoxLayout()
        self.view = combo(('Available','My tasks','Archived','All records'))
        self.category = combo(('All types',*CATEGORIES))
        self.min_pay = QDoubleSpinBox(); self.min_pay.setRange(0,100000); self.min_pay.setPrefix('USD min '); self.min_pay.setValue(ctx.settings.min_pay_usd)
        self.unit = combo(UNITS)
        self.minutes = QSpinBox(); self.minutes.setRange(0,100000); self.minutes.setSpecialValueText('Any duration'); self.minutes.setSuffix(' min')
        for widget in (self.view,self.category,self.min_pay,self.unit,self.minutes): filters.addWidget(widget)
        layout.addLayout(filters)
        options = QHBoxLayout()
        self.unknown = QCheckBox('Include unknown pay / other currencies')
        options.addWidget(self.unknown)
        options.addWidget(th.button('Clear filters', 'ghost', 'Reset to $2 per task and any duration', self.clear_filters))
        options.addStretch(1); layout.addLayout(options)
        layout.addWidget(th.label('The USD minimum is compared only within the selected pay unit. My tasks and history retain all payment amounts. Expired opportunities are hidden from Available.', 'small', wrap=True))
        self.summary = th.label('', 'small', wrap=True); layout.addWidget(self.summary)
        self.table = QTableWidget(0,8)
        self.table.setHorizontalHeaderLabels(['Select','Task / platform','Type','Advertised pay','Time','Deadline','Eligibility','Progress'])
        self.table.setSelectionBehavior(QTableWidget.SelectRows); self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers); self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True); layout.addWidget(self.table,1)
        actions = QHBoxLayout()
        actions.addWidget(th.button('Add to my tasks', 'primary', 'Save the checked opportunities', self.add_checked))
        actions.addWidget(th.button('Edit details', 'default', '', self.edit_task))
        actions.addWidget(th.button('Open task', 'default', '', self.open_task))
        self.stage = combo(STAGES[1:])
        actions.addWidget(self.stage)
        actions.addWidget(th.button('Update progress', 'default', 'Apply to the highlighted task; Paid asks for the amount received', self.update_stage))
        actions.addStretch(1); layout.addLayout(actions)
        self.details = QTextBrowser(); self.details.setMaximumHeight(160); layout.addWidget(self.details)
        self.earnings = th.label('', 'small', wrap=True); layout.addWidget(self.earnings)
        self.table.itemChanged.connect(self.check_changed)
        self.table.itemSelectionChanged.connect(self.show_details)
        for widget in (self.view,self.category,self.unit): widget.currentTextChanged.connect(self.filter_changed)
        self.query.textChanged.connect(self.filter_changed)
        self.min_pay.valueChanged.connect(self.filter_changed); self.minutes.valueChanged.connect(self.filter_changed)
        self.unknown.toggled.connect(self.filter_changed)
        self.refresh()

    def filter_changed(self, *_):
        self.checked.clear()
        self.ctx.settings.min_pay_usd = self.min_pay.value()
        self.ctx.settings.task_search_query = self.query.text()
        self.ctx.save_settings(self.ctx.settings)
        self.refresh()

    def platforms_changed(self, *_):
        self.ctx.settings.task_platforms_enabled = [name for name, box in self.platform_boxes.items() if box.isChecked()]
        self.ctx.save_settings(self.ctx.settings)

    def search_websites(self):
        names = [name for name, box in self.platform_boxes.items() if box.isChecked()]
        if not names:
            self.ctx.notify('Tick at least one task website first.', 'info')
            return
        terms = task_search_terms(self.query.text(), self.category.currentText())
        self.ctx.settings.task_search_query = self.query.text()
        self.ctx.settings.task_platforms_enabled = names
        self.ctx.save_settings(self.ctx.settings)
        opened = [name for name in names if th.open_in_browser(task_platform(name).search_url(terms))]
        if not opened:
            self.web_status.setText('The browser could not be opened. Copy the website links from the tooltips and try again.')
            self.ctx.notify('The browser could not be opened for the task websites.', 'warning')
            return
        self.web_status.setText(f"Opened {len(opened)} task website(s) for '{terms}' in your browser. Sign in, pick real offers, then use Add task details to record them here.")
        self.ctx.notify(f"Opened {len(opened)} task website(s) in your browser for '{terms}'. Sign in there; availability and eligibility stay on the platform.", 'success')

    def clear_filters(self):
        for widget in (self.query,self.category,self.min_pay,self.unit,self.minutes,self.unknown): widget.blockSignals(True)
        self.query.clear(); self.category.setCurrentIndex(0); self.min_pay.setValue(2); self.unit.setCurrentText('task'); self.minutes.setValue(0); self.unknown.setChecked(False)
        for widget in (self.query,self.category,self.min_pay,self.unit,self.minutes,self.unknown): widget.blockSignals(False)
        self.filter_changed()

    def refresh(self):
        recommendations = recommended_task_sources(self.ctx.profile)
        if recommendations:
            links = ' · '.join(f'<a href="{escape(item["url"])}">{escape(item["title"])}</a>' for item in recommendations)
            self.recommendations.setHtml(f'<b>Profile suggestions:</b> {links}')
        else:
            self.recommendations.setHtml('<span>Profile suggestions: add your experience and skills in Profile.</span>')
        records = self.store.tasks()
        self.visible = [task for task in records if matches_filters(task, query=self.query.text(), category=self.category.currentText(),
            minimum=self.min_pay.value(), unit=self.unit.currentText(), minutes=self.minutes.value(), view=self.view.currentText(), include_unknown=self.unknown.isChecked())]
        self.table.blockSignals(True); self.table.setRowCount(len(self.visible))
        for row, task in enumerate(self.visible):
            check = QTableWidgetItem(); check.setData(Qt.UserRole,task.task_id)
            if task.status == 'Available' and not task.expired and task.eligibility != 'Not eligible':
                check.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
                check.setCheckState(Qt.Checked if task.task_id in self.checked else Qt.Unchecked)
            else: check.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row,0,check)
            values = [task.title+' — '+task.platform, task.category, task.pay_label, f'{task.minutes} min' if task.minutes else 'Unknown',
                      (task.deadline + (' (expired)' if task.expired else '')) or 'Unknown', task.eligibility, task.status]
            for col,value in enumerate(values,1): self.table.setItem(row,col,QTableWidgetItem(value))
        self.table.blockSignals(False)
        self.summary.setText(f'{len(self.visible)} shown / {len(records)} recorded. Manually added opportunities; confirm availability on the platform.' if records else 'No real tasks added yet. Search the task websites above, then use Add task details. Demo tasks are not shown or added to applications.')
        totals=self.store.earnings()
        self.earnings.setText('Payments recorded: '+(' · '.join(f'{value:,.2f} {currency}' for currency,value in sorted(totals.items())) or 'None yet')+' — actual receipts only; currencies are kept separate.')
        self.details.clear()
        if self.visible: self.table.selectRow(0); self.show_details()

    def check_changed(self,item):
        if item.column()!=0: return
        task_id=item.data(Qt.UserRole)
        if item.checkState()==Qt.Checked: self.checked.add(task_id)
        else: self.checked.discard(task_id)

    def selected(self):
        row=self.table.currentRow()
        return self.visible[row] if 0 <= row < len(self.visible) else None

    def show_details(self):
        task=self.selected()
        if not task: self.details.clear(); return
        reasons = recommended_task_sources(self.ctx.profile)
        category_names={'Data entry':'Data entry and web research','Web research':'Data entry and web research','Categorisation':'Product data and categorisation','Testing':'Website and application testing'}
        reason=next((r['reason'] for r in reasons if r['title']==category_names.get(task.category)), 'No specific evidence in your saved profile for this category; review the requirements.')
        self.details.setHtml(f'<b>{escape(task.title)}</b><p>{escape(reason)}</p><p>Eligibility: {escape(task.eligibility)}. Profile relevance does not confirm platform qualification.</p><p>{escape(task.description).replace(chr(10), "<br>")}</p>')

    def edit(self, task):
        dialog=TaskDialog(task,self)
        while dialog.exec()==QDialog.Accepted:
            try:
                saved,changed=self.store.save(dialog.value())
            except ValueError as error:
                dialog.error.setText(str(error)); continue
            self.refresh()
            self.ctx.notify('Task details saved. Use the checkbox to add it to My tasks.' if changed else 'That task is already recorded. Its progress and payment history were kept.', 'success' if changed else 'info')
            break

    def add_task(self): self.edit(PaidTask())
    def edit_task(self):
        if self.selected(): self.edit(self.selected())
    def open_task(self):
        if self.selected(): th.open_in_browser(self.selected().url)

    def add_checked(self):
        if not self.checked:
            self.ctx.notify('Tick available tasks first.', 'info'); return
        count=0
        for task in self.visible:
            if task.task_id in self.checked and task.status=='Available':
                try: self.store.set_stage(task.task_id,'Saved'); count+=1
                except ValueError as error: self.ctx.notify(str(error),'warning')
        self.checked.clear(); self.refresh()
        self.ctx.notify(f'Added {count} selected task(s). Open My tasks to track progress.', 'success')

    def update_stage(self):
        task=self.selected()
        if not task: return
        status=self.stage.currentText()
        if task.status=='Available' and status!='Archived':
            self.ctx.notify('Tick this opportunity and use Add to my tasks first.', 'info'); return
        received=None
        if status=='Paid':
            received,ok=QInputDialog.getDouble(self,'Record payment',f'Amount actually received ({task.currency}):',task.received,0.01,10000000,2)
            if not ok: return
        try: self.store.set_stage(task.task_id,status,received)
        except ValueError as error: self.ctx.notify(str(error),'warning'); return
        self.refresh()
        self.ctx.notify(f'Task marked {status}.', 'success')
