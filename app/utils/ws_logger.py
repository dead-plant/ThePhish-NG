import logging

log = logging.getLogger(__name__)

class WebSocketLogError(RuntimeError):
	"""Raised when a websocket log message cannot be emitted."""


# Class used for logging with different levels of severity
# The constructor takes the socketio object and the socket id of the client to send logs to
class WebSocketLogger:
	def __init__(self, socketio, sid):
		if socketio is None or not callable(getattr(socketio, "emit", None)):
			log.error("Invalid websocket logger socketio argument: missing callable emit method")
			raise TypeError("socketio must provide a callable emit method")
		if sid is None:
			log.error("Invalid websocket logger sid argument: sid is required")
			raise ValueError("sid is required")
		self.socketio = socketio
		self.sid = sid
		log.debug("WebSocket logger initialized for sid=%s", sid)

	def _emit(self, event: str, level: str, message):
		log.debug("Emitting websocket %s log to sid=%s: %s", level, self.sid, message)
		try:
			self.socketio.emit(event, message, to = self.sid)
		except Exception as e:
			log.error("Failed to emit websocket %s log to sid=%s", level, self.sid, exc_info=True)
			raise WebSocketLogError("failed to emit websocket {} log".format(level)) from e

	def emit_info(self, message):
		self._emit("logInfo", "info", message)

	def emit_warning(self, message):
		self._emit("logWarning", "warning", message)

	def emit_error(self, message):
		self._emit("logError", "error", message)
