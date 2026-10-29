"""Transport-independent ownership of one pending script and one active run."""

import logging
from threading import Event, RLock, Thread

from .scratch_parser import parse_program, format_program
from .scratch_runner import ExecutionCancelled, validate_program


logger = logging.getLogger(__name__)


class RobotSession:
    def __init__(self, *, executor=None, notify=None):
        self.executor = executor
        self.notify = notify or (lambda event: None)
        self._program = None
        self._lock = RLock()
        self._worker = None
        self._cancel = None
        self._busy = False
        self._closed = False

    def _emit(self, event):
        try:
            self.notify(event)
        except Exception as error:
            if self._cancel is not None:
                self._cancel.set()
            logger.warning("Khong gui duoc phan hoi: %s", error)

    def dispatch(self, request):
        with self._lock:
            if self._closed:
                return {"ok": False, "error": "Phien da dong."}
            action = request.get("action")
            if action == "upload":
                self._program = None
                try:
                    program = parse_program(request.get("code"))
                    validate_program(program)
                except ValueError as error:
                    return {"ok": False, "error": str(error)}
                self._program = program
                logger.info("UPLOAD hop le.\n%s", format_program(program))
                return {"ok": True, "status": "uploaded", "commands": program.command_count,
                        "markers": program.marker_count}
            if action == "run":
                if self._busy:
                    return {"ok": False, "error": "Robot dang ban; khong xep hang RUN."}
                if self._program is None:
                    return {"ok": False, "error": "Chua co kich ban hop le; can upload."}
                if self.executor is None:
                    logger.info("PREVIEW EXECUTE.\n%s", format_program(self._program))
                    return {"ok": True, "status": "preview", "commands": self._program.command_count}
                self._cancel = Event()
                self._busy = True
                self._worker = Thread(target=self._execute, args=(self._program, self._cancel),
                                      name="script-worker", daemon=False)
                try:
                    self._worker.start()
                except Exception as error:
                    self._worker = None
                    self._busy = False
                    return {"ok": False, "error": str(error)}
                return {"ok": True, "status": "accepted"}
            if action == "stop":
                if self._cancel is not None:
                    self._cancel.set()
                return {"ok": True, "status": "stopping" if self._busy else "idle"}
            if action in ("ping", "status"):
                return {"ok": True, "status": "executing" if self._busy else "idle",
                        "uploaded": self._program is not None,
                        "mode": "preview" if self.executor is None else "runner"}
            return {"ok": False, "error": "Action chua duoc ho tro."}

    def _execute(self, program, cancel):
        status = "done"
        self._emit({"event": "status", "status": "executing"})
        try:
            self.executor(program, stop_event=cancel,
                          reporter=lambda block_id: self._emit({"event": "block", "block_id": block_id}))
            if cancel.is_set():
                status = "stopped"
        except ExecutionCancelled:
            status = "stopped"
        except Exception as error:
            status = "error"
            self._emit({"event": "error", "error": str(error)})
            logger.error("Loi chay kich ban: %s", error)
        finally:
            with self._lock:
                self._busy = False
                self._emit({"event": "status", "status": status})

    def reset(self):
        with self._lock:
            self._program = None
            if self._cancel is not None:
                self._cancel.set()

    def wait(self, timeout=None):
        with self._lock:
            worker = self._worker
        if worker is not None:
            worker.join(timeout)

    def close(self):
        with self._lock:
            self._closed = True
            self.reset()
        self.wait()
