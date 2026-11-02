'''
pickmix: background workers to run work off of the main GUI thread
'''

# Import external dependencies
from collections.abc import Callable
from PySide6.QtCore import QObject, QThreadPool, Signal, Slot

# _Dispatcher: lives on the GUI thread; calls emitted from any thread run there
class _Dispatcher(QObject):
    call = Signal(object)

    # __init__: route the signal to the slot below
    def __init__(self) -> None:
        super().__init__()
        self.call.connect(self._invoke)

    # _invoke: run a posted callable
    @Slot(object)
    def _invoke(self, fn: Callable[[], None]) -> None:
        fn()

# _dispatcher: created on first use, which must be on the GUI thread
_dispatcher: _Dispatcher | None = None

# post: run fn on the GUI thread; callable from any thread once something has used the dispatcher from the GUI thread
def post(fn: Callable[[], None]) -> None:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = _Dispatcher()
    _dispatcher.call.emit(fn)

# run_in_background: run fn on the thread pool, then on_done(result) or on_failed(message) on the GUI thread
def run_in_background[T](fn: Callable[[], T], on_done: Callable[[T], None], on_failed: Callable[[str], None]) -> None:
    # touch the dispatcher here so it is created on the GUI thread
    post(lambda: None)

    # job: the pool runs this
    def job() -> None:
        try:
            result = fn()
        except Exception as e:
            message = f'{type(e).__name__}: {e}'
            post(lambda: on_failed(message))
            return
        post(lambda: on_done(result))

    QThreadPool.globalInstance().start(job)
