"""Execute a complete application-service call outside the GUI event thread."""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(object)
    finished = Signal()


class DatabaseWorker(QRunnable):
    """Run one callable; service calls create their own Unit of Work and Session."""

    def __init__(self, operation: Callable[[], object]) -> None:
        super().__init__()
        self._operation: Callable[[], object] | None = operation
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        operation = self._operation
        self._operation = None
        if operation is None:
            self.signals.error.emit(RuntimeError("Database worker was already executed"))
            self.signals.finished.emit()
            return
        try:
            result = operation()
        except Exception as error:
            self.signals.error.emit(error)
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()


class DatabaseTaskRunner(QObject):
    """Own active workers so Qt cannot collect them before completion."""

    def __init__(self, thread_pool: QThreadPool, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread_pool = thread_pool
        self._workers: set[DatabaseWorker] = set()

    def submit(
        self,
        operation: Callable[[], object],
        *,
        on_result: Callable[[Any], None],
        on_error: Callable[[BaseException], None],
        on_finished: Callable[[], None] | None = None,
    ) -> DatabaseWorker:
        worker = DatabaseWorker(operation)
        self._workers.add(worker)
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error)

        def finished() -> None:
            self._workers.discard(worker)
            if on_finished is not None:
                on_finished()

        worker.signals.finished.connect(finished)
        self._thread_pool.start(worker)
        return worker
