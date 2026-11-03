"""One product-owned wall-clock window shared by a review and its protocol repair."""
from contextlib import contextmanager
from contextvars import ContextVar
import time

MAX_SECONDS=60
SETTLE_SECONDS=5
_WINDOW=ContextVar('feedback_review_window',default=None)


class ReviewTimeout(TimeoutError):
    pass


class ReviewWindow:
    def __init__(self,request):
        seconds=min(MAX_SECONDS,request['limits']['call_timeout'])
        from .task_budgets import current
        scope=current()
        if scope:
            remaining=scope.ledger.view(scope.member['id'])['remaining']['time_ms']/1000
            seconds=min(seconds,max(0,remaining-SETTLE_SECONDS))
        self.deadline=time.monotonic()+seconds

    def remaining(self):return max(0,self.deadline-time.monotonic())
    def expired(self):return self.remaining()<=0
    def check(self):
        if self.expired():raise ReviewTimeout('独立审阅时间窗口已到，候选和实际回执保留，未算验收通过。')

    @contextmanager
    def active(self):
        self.check();token=_WINDOW.set(self)
        try:yield self
        finally:_WINDOW.reset(token)


def current_window():return _WINDOW.get()
