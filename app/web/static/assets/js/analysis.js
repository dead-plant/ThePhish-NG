(function(root, factory) {
	"use strict";
	const api = factory();
	if (typeof module === "object" && module.exports) {
		module.exports = api;
	}
	if (root) {
		root.ThePhishAnalysis = api;
	}
})(typeof window !== "undefined" ? window : null, function() {
	"use strict";

	const activeStatuses = new Set(["pending", "running"]);
	const terminalStatuses = new Set(["finished", "failed"]);
	const verdicts = new Set(["Safe", "Suspicious", "Malicious"]);
	const loadFallback = "The analysis could not be loaded. Please try again later.";
	const failureFallback = "The analysis failed without a recorded error.";

	class DisplayError extends Error {}

	async function readJson(response) {
		let body;
		try {
			body = await response.json();
		} catch (_error) {
			throw new DisplayError(loadFallback);
		}
		if (!response.ok) {
			const message = body && body.error && typeof body.error.message === "string"
				? body.error.message
				: loadFallback;
			throw new DisplayError(message);
		}
		return body;
	}

	function normalizeLogEntry(value) {
		if (
			!value
			|| !Number.isInteger(value.seq)
			|| value.seq < 0
			|| typeof value.level !== "string"
			|| typeof value.message !== "string"
			|| (value.timestamp !== undefined && typeof value.timestamp !== "string")
		) {
			return null;
		}
		return {
			seq: value.seq,
			timestamp: value.timestamp,
			level: value.level,
			message: value.message,
		};
	}

	function parseEventData(event) {
		try {
			return JSON.parse(event.data);
		} catch (_error) {
			return null;
		}
	}

	function createAnalysisController({analysisId, fetchFn, EventSourceCtor, view}) {
		const renderedSequences = new Set();
		const encodedId = encodeURIComponent(analysisId);
		let source = null;

		function closeStream() {
			if (source) {
				source.close();
				source = null;
			}
		}

		function addLogEntry(rawEntry) {
			const entry = normalizeLogEntry(rawEntry);
			if (!entry || renderedSequences.has(entry.seq)) {
				return;
			}
			const followTail = view.isLogNearBottom();
			renderedSequences.add(entry.seq);
			view.insertLogEntry(entry);
			if (followTail) {
				view.scrollLogToBottom();
			}
		}

		function showTerminalState(state) {
			closeStream();
			if (state.status === "finished") {
				if (!verdicts.has(state.verdict)) {
					view.setStatus("unavailable");
					view.showFatalError("The finished analysis does not contain a valid verdict.");
					return;
				}
				view.setStatus("finished");
				view.showVerdict(state.verdict);
				return;
			}
			view.setStatus("failed");
			view.showFailure(
				typeof state.error === "string" && state.error
					? state.error
					: failureFallback,
			);
		}

		function applyState(state) {
			if (!state || typeof state.status !== "string") {
				throw new DisplayError(loadFallback);
			}
			if (terminalStatuses.has(state.status)) {
				showTerminalState(state);
				return;
			}
			if (!activeStatuses.has(state.status)) {
				throw new DisplayError(loadFallback);
			}
			view.setStatus(state.status);
			openStream();
		}

		function openStream() {
			if (source) {
				return;
			}
			source = new EventSourceCtor(`/api/analyses/${encodedId}/stream`);
			source.addEventListener("log", (event) => {
				const data = parseEventData(event);
				if (data) {
					addLogEntry(data);
				}
			});
			source.addEventListener("status", (event) => {
				const data = parseEventData(event);
				if (!data || typeof data.status !== "string") {
					return;
				}
				try {
					if (terminalStatuses.has(data.status)) {
						showTerminalState(data);
					} else if (activeStatuses.has(data.status)) {
						view.setStatus(data.status);
					}
				} catch (_error) {
					view.showFatalError(loadFallback);
				}
			});
			source.addEventListener("open", () => view.clearConnectionWarning());
			source.addEventListener("error", () => view.showConnectionWarning());
		}

		async function load() {
			view.clearAlert();
			view.setStatus("loading");
			try {
				const [stateResponse, logResponse] = await Promise.all([
					fetchFn(`/api/analyses/${encodedId}`),
					fetchFn(`/api/analyses/${encodedId}/log`),
				]);
				const [state, entries] = await Promise.all([
					readJson(stateResponse),
					readJson(logResponse),
				]);
				if (!Array.isArray(entries)) {
					throw new DisplayError(loadFallback);
				}
				entries
					.map(normalizeLogEntry)
					.filter((entry) => entry !== null)
					.sort((left, right) => left.seq - right.seq)
					.forEach(addLogEntry);
				applyState(state);
			} catch (error) {
				closeStream();
				view.setStatus("unavailable");
				view.showFatalError(
					error instanceof DisplayError ? error.message : loadFallback,
				);
			}
		}

		return {
			load,
			dispose: closeStream,
		};
	}

	function createAnalysisView(document) {
		const status = document.getElementById("analysisStatus");
		const alert = document.getElementById("analysisAlert");
		const log = document.getElementById("analysisLog");
		const entries = document.getElementById("analysisLogEntries");
		const result = document.getElementById("analysisResult");
		const resultTitle = document.getElementById("analysisResultTitle");
		const resultMessage = document.getElementById("analysisResultMessage");

		const statusLabels = {
			loading: "Loading analysis…",
			pending: "Analysis pending…",
			running: "Analyzing…",
			finished: "Analysis complete",
			failed: "Analysis failed",
			unavailable: "Analysis unavailable",
		};
		const verdictMessages = {
			Safe: "The e-mail has been classified as SAFE. The case has been closed and the response has been sent.",
			Suspicious: "The e-mail has been classified as SUSPICIOUS. The case has been left open for further investigation.",
			Malicious: "The e-mail has been classified as MALICIOUS. The case has been closed, submitted to MISP, and the response has been sent.",
		};

		function clearAlert() {
			alert.textContent = "";
			alert.className = "alert d-none analysis-alert";
		}

		function setStatus(value) {
			status.textContent = statusLabels[value] || value;
			status.className = `analysis-status analysis-status-${value}`;
		}

		function insertLogEntry(entry) {
			const line = document.createElement("div");
			const normalizedLevel = entry.level.toLowerCase();
			line.className = `analysis-log-line analysis-log-${normalizedLevel}`;
			line.dataset.seq = String(entry.seq);
			line.textContent = `[${entry.level.toUpperCase()}]: ${entry.message}`;
			const next = Array.from(entries.children).find(
				(child) => Number(child.dataset.seq) > entry.seq,
			);
			entries.insertBefore(line, next || null);
		}

		function isLogNearBottom() {
			return log.scrollHeight - log.scrollTop - log.clientHeight < 48;
		}

		function scrollLogToBottom() {
			log.scrollTop = log.scrollHeight;
		}

		function showVerdict(verdict) {
			result.className = `analysis-result analysis-result-${verdict.toLowerCase()}`;
			resultTitle.textContent = verdict.toUpperCase();
			resultMessage.textContent = verdictMessages[verdict];
		}

		function showFailure(message) {
			result.className = "analysis-result analysis-result-failed";
			resultTitle.textContent = "FAILED";
			resultMessage.textContent = message;
		}

		function showFatalError(message) {
			alert.className = "alert alert-danger analysis-alert";
			alert.textContent = message;
		}

		function showConnectionWarning() {
			alert.className = "alert alert-warning analysis-alert";
			alert.textContent = "The live connection was interrupted. Reconnecting…";
		}

		function clearConnectionWarning() {
			if (alert.classList.contains("alert-warning")) {
				clearAlert();
			}
		}

		return {
			clearAlert,
			setStatus,
			insertLogEntry,
			isLogNearBottom,
			scrollLogToBottom,
			showVerdict,
			showFailure,
			showFatalError,
			showConnectionWarning,
			clearConnectionWarning,
		};
	}

	function boot(window) {
		const controller = createAnalysisController({
			analysisId: window.document.body.dataset.analysisId,
			fetchFn: window.fetch.bind(window),
			EventSourceCtor: window.EventSource,
			view: createAnalysisView(window.document),
		});
		window.addEventListener("pagehide", controller.dispose, {once: true});
		controller.load();
	}

	if (typeof window !== "undefined" && window.document) {
		window.document.addEventListener("DOMContentLoaded", () => boot(window));
	}

	return {
		createAnalysisController,
		createAnalysisView,
		normalizeLogEntry,
	};
});
