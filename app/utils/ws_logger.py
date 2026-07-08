import logging

log = logging.getLogger(__name__)

# Class used for logging with different levels of severity
# The constructor takes the socketio object and the socket id of the client to send logs to
class WebSocketLogger:

	def __init__(self, socketio, sid):
		self.socketio = socketio
		self.sid = sid
		log.debug("WebSocket logger initialized for sid=%s", sid)

	def _emit(self, event: str, level: str, message):
		log.debug("Emitting websocket %s log to sid=%s: %s", level, self.sid, message)
		try:
			self.socketio.emit(event, message, to = self.sid)
		except Exception:
			log.error("Failed to emit websocket %s log to sid=%s", level, self.sid, exc_info=True)
			raise

	def emit_debug(self, message):
		self._emit("logDebug", "debug", message)

	def emit_info(self, message):
		self._emit("logInfo", "info", message)

	def emit_warning(self, message):
		self._emit("logWarning", "warning", message)

	def emit_error(self, message):
		self._emit("logError", "error", message)
