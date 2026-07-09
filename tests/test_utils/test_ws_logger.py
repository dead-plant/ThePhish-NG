import unittest
from unittest.mock import Mock, patch

from app.utils.ws_logger import WebSocketLogError, WebSocketLogger


class WebSocketLoggerTests(unittest.TestCase):
    def test_constructor_requires_socketio_with_callable_emit(self):
        invalid_socketios = [None, object(), Mock(emit="not-callable")]

        for socketio in invalid_socketios:
            with self.subTest(socketio=socketio):
                with self.assertRaises(TypeError):
                    WebSocketLogger(socketio, "sid-123")

    def test_constructor_requires_sid(self):
        with self.assertRaises(ValueError):
            WebSocketLogger(Mock(emit=Mock()), None)

    def test_emit_methods_send_expected_websocket_events_to_sid(self):
        socketio = Mock()
        logger = WebSocketLogger(socketio, "sid-123")

        logger.emit_info("info message")
        logger.emit_warning("warning message")
        logger.emit_error("error message")

        socketio.emit.assert_any_call("logInfo", "info message", to="sid-123")
        socketio.emit.assert_any_call("logWarning", "warning message", to="sid-123")
        socketio.emit.assert_any_call("logError", "error message", to="sid-123")
        self.assertEqual(socketio.emit.call_count, 3)

    def test_emit_wraps_socketio_errors(self):
        socketio = Mock()
        socketio.emit.side_effect = RuntimeError("socket failed")
        logger = WebSocketLogger(socketio, "sid-123")

        with patch("app.utils.ws_logger.log"):
            with self.assertRaises(WebSocketLogError) as error:
                logger.emit_error("error message")

        self.assertIsInstance(error.exception.__cause__, RuntimeError)
        socketio.emit.assert_called_once_with("logError", "error message", to="sid-123")


if __name__ == "__main__":
    unittest.main()
