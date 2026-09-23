"""Local paid-task records, deliberately separate from job applications."""
from dataclasses import dataclass, asdict, field
from datetime import date
import json
import re
import uuid
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

STAGES = ('Available', 'Saved', 'Started', 'Submitted', 'Approved', 'Paid', 'Archived')
CATEGORIES = ('Data entry', 'Web research', 'Categorisation', 'Testing', 'Other')
UNITS = ('task', 'batch', 'hour')
ELIGIBILITY = ('Not checked', 'Assessment required', 'Eligible (confirmed by me)', 'Not eligible')


def canonical_url(url):
    parts = urlsplit(url.strip())
    if parts.scheme not in ('http', 'https') or not parts.netloc or parts.username or parts.password:
        raise ValueError('Enter a valid public https:// or http:// task link without sign-in credentials.')
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith('utm_') and k.lower() not in ('fbclid', 'gclid')]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip('/'), urlencode(sorted(query)), ''))


@dataclass
class PaidTask:
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    title: str = ''
    platform: str = 'Clickworker'
    url: str = ''
    category: str = 'Data entry'
    amount: float | None = None
    currency: str = 'USD'
    unit: str = 'task'
    minutes: int = 0
    deadline: str = ''
    eligibility: str = 'Not checked'
    description: str = ''
    status: str = 'Available'
    received: float = 0
    history: list = field(default_factory=list)

    @property
    def expired(self):
        return bool(self.deadline and date.fromisoformat(self.deadline) < date.today())

    @property
    def pay_label(self):
        return 'Pay unknown' if self.amount is None else f'{self.amount:,.2f} {self.currency} / {self.unit}'

    @property
    def identity(self):
        return re.sub(r'\s+', ' ', self.platform.strip().casefold()) + '|' + re.sub(r'\s+', ' ', self.title.strip().casefold())


class TaskStore:
    def __init__(self, workspace):
        self.workspace = workspace
        with workspace._lock:
            workspace._conn.execute('CREATE TABLE IF NOT EXISTS paid_tasks (task_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            workspace._conn.commit()

    def tasks(self):
        with self.workspace._lock:
            rows = self.workspace._conn.execute('SELECT payload FROM paid_tasks ORDER BY rowid DESC').fetchall()
            return [PaidTask(**json.loads(row[0])) for row in rows]

    def save(self, task):
        task.title, task.platform = task.title.strip(), task.platform.strip()
        if not task.title or not task.platform:
            raise ValueError('Enter a task title and platform.')
        task.url = canonical_url(task.url)
        if task.deadline:
            try: date.fromisoformat(task.deadline)
            except ValueError: raise ValueError('Use YYYY-MM-DD for the deadline, or leave it blank.')
        if task.status not in STAGES or task.unit not in UNITS or task.category not in CATEGORIES or task.eligibility not in ELIGIBILITY:
            raise ValueError('Choose one of the available task options.')
        if task.amount is not None and task.amount < 0 or task.minutes < 0 or task.received < 0:
            raise ValueError('Payment and time cannot be negative.')
        if not re.fullmatch('[A-Z]{3}', task.currency):
            raise ValueError('Enter a three-letter currency such as USD, EUR or KES.')
        with self.workspace._lock:
            for old in self.tasks():
                if old.task_id == task.task_id and old.received > 0 and old.currency != task.currency:
                    raise ValueError('The currency cannot change after a payment has been recorded.')
                if old.task_id != task.task_id and (old.url == task.url or old.identity == task.identity):
                    return old, False
            self.workspace._conn.execute('INSERT INTO paid_tasks VALUES (?,?) ON CONFLICT(task_id) DO UPDATE SET payload=excluded.payload',
                                         (task.task_id, json.dumps(asdict(task))))
            self.workspace._conn.commit()
        return task, True

    def set_stage(self, task_id, status, received=None):
        if status not in STAGES: raise ValueError('Unknown task status.')
        with self.workspace._lock:
            task = next(t for t in self.tasks() if t.task_id == task_id)
            if status == 'Saved' and (task.expired or task.eligibility == 'Not eligible'):
                raise ValueError('Expired or ineligible tasks cannot be added to My tasks.')
            if status == 'Paid':
                if received is None or received <= 0: raise ValueError('Enter the amount actually received.')
                task.received = received
            task.history.append({'date': date.today().isoformat(), 'from': task.status, 'to': status})
            task.status = status
            self.save(task)
            return task

    def earnings(self):
        totals = {}
        for task in self.tasks():
            if task.received > 0: totals[task.currency] = round(totals.get(task.currency, 0) + task.received, 2)
        return totals


def matches_filters(task, *, query='', category='All types', minimum=2, unit='task', minutes=0, view='Available', include_unknown=False):
    if view == 'Available' and (task.status != 'Available' or task.expired): return False
    if view == 'My tasks' and task.status in ('Available', 'Archived'): return False
    if view == 'Archived' and task.status != 'Archived': return False
    if category != 'All types' and task.category != category: return False
    if query.casefold() not in (task.title+' '+task.platform+' '+task.description).casefold(): return False
    if minutes and (not task.minutes or task.minutes > minutes): return False
    # Minimum-pay screening applies to opportunities, never hides work already underway.
    if view == 'Available' and minimum:
        if task.amount is None or task.currency != 'USD': return include_unknown
        if task.unit != unit or task.amount < minimum: return False
    return True
