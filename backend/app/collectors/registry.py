"""source_type -> collector instance. New sources plug in here without touching the AI engine."""
from app.collectors.early_signals import EarlySignalCollector
from app.collectors.jobs import JobsCollector
from app.collectors.news import NewsCollector
from app.collectors.pages import PagesCollector

COLLECTORS = {
    "page": PagesCollector(),
    "jobs": JobsCollector(),
    "news": NewsCollector(),
    "early_signal": EarlySignalCollector(),
}
