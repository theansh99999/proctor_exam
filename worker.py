"""
worker.py
---------
Standalone Background Worker CLI for ExamProctor:
Runs periodic background tasks (reminders, auto-finalizations, sync retries).
Usage:
    python worker.py [interval_seconds]
"""
import sys
import signal
from modules.background.worker import BackgroundWorker, signal_handler

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    worker = BackgroundWorker(check_interval_seconds=interval)
    worker.start()
