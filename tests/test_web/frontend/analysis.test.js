"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
	buildTheHiveCaseUrl,
	createAnalysisController,
	createAnalysisView,
	installAnalysisLifecycle,
	normalizeLogEntry,
} = require("../../../app/web/static/assets/js/analysis.js");
const {
	createAnalysisDocument,
} = require("./fake-dom.js");

function jsonResponse(status, body) {
	return {
		ok: status >= 200 && status < 300,
		status,
		async json() {
			return body;
		},
	};
}

class FakeEventSource {
	static instances = [];

	constructor(url) {
		this.url = url;
		this.closed = false;
		this.listeners = new Map();
		FakeEventSource.instances.push(this);
	}

	addEventListener(name, listener) {
		if (!this.listeners.has(name)) {
			this.listeners.set(name, []);
		}
		this.listeners.get(name).push(listener);
	}

	emit(name, data) {
		for (const listener of this.listeners.get(name) || []) {
			listener(data === undefined ? {} : {data: JSON.stringify(data)});
		}
	}

	close() {
		this.closed = true;
	}
}

function createView() {
	return {
		actions: [],
		alert: null,
		case: null,
		connectionWarning: false,
		entries: [],
		failure: null,
		nearBottom: true,
		statuses: [],
		verdict: null,
		clearAlert() {
			this.alert = null;
		},
		showCase(caseId, caseNumber) {
			this.case = {caseId, caseNumber};
			this.actions.push("case");
		},
		setStatus(status) {
			this.statuses.push(status);
		},
		insertLogEntry(entry) {
			this.entries.push(entry);
			this.entries.sort((left, right) => left.seq - right.seq);
		},
		isLogNearBottom() {
			this.actions.push("check-tail");
			return this.nearBottom;
		},
		scrollLogToBottom() {
			this.actions.push("scroll-now");
		},
		scrollLogToBottomAfterLayout() {
			this.actions.push("scroll-after-layout");
		},
		showVerdict(verdict) {
			this.verdict = verdict;
			this.actions.push(`verdict:${verdict}`);
		},
		showFailure(message) {
			this.failure = message;
			this.actions.push("failure");
		},
		showFatalError(message) {
			this.alert = message;
		},
		showConnectionWarning() {
			this.connectionWarning = true;
		},
		clearConnectionWarning() {
			this.connectionWarning = false;
		},
	};
}

function fetchSequence(responses, calls) {
	return async (url) => {
		calls.push(url);
		if (responses.length === 0) {
			throw new Error("Unexpected fetch");
		}
		return responses.shift();
	};
}

function deferred() {
	let resolve;
	const promise = new Promise((promiseResolve) => {
		resolve = promiseResolve;
	});
	return {promise, resolve};
}

test("loads state before requesting the persisted log snapshot", async () => {
	FakeEventSource.instances = [];
	const stateResponse = deferred();
	const logRequested = deferred();
	const calls = [];
	const view = createView();
	const controller = createAnalysisController({
		analysisId: "ordered",
		fetchFn: async (url) => {
			calls.push(url);
			if (url.endsWith("/log")) {
				logRequested.resolve();
				return jsonResponse(200, []);
			}
			return stateResponse.promise;
		},
		EventSourceCtor: FakeEventSource,
		view,
	});

	const loadPromise = controller.load();

	assert.deepEqual(calls, ["/api/analyses/ordered"]);
	stateResponse.resolve(jsonResponse(200, {status: "finished", verdict: "Safe"}));
	await logRequested.promise;
	assert.deepEqual(calls, [
		"/api/analyses/ordered",
		"/api/analyses/ordered/log",
	]);
	await loadPromise;
});

test("dispose suppresses pending load work before rendering or opening a stream", async () => {
	FakeEventSource.instances = [];
	const stateResponse = deferred();
	const calls = [];
	const view = createView();
	const controller = createAnalysisController({
		analysisId: "disposed",
		fetchFn: async (url) => {
			calls.push(url);
			if (url.endsWith("/log")) {
				return jsonResponse(200, []);
			}
			return stateResponse.promise;
		},
		EventSourceCtor: FakeEventSource,
		view,
	});

	const loadPromise = controller.load();
	controller.dispose();
	stateResponse.resolve(jsonResponse(200, {status: "running"}));
	await loadPromise;

	assert.deepEqual(calls, ["/api/analyses/disposed"]);
	assert.deepEqual(view.statuses, ["loading"]);
	assert.deepEqual(view.entries, []);
	assert.equal(view.verdict, null);
	assert.equal(view.failure, null);
	assert.equal(view.alert, null);
	assert.equal(FakeEventSource.instances.length, 0);
});

test("finished direct load renders sorted history and verdict without a stream", async () => {
	FakeEventSource.instances = [];
	const calls = [];
	const view = createView();
	const controller = createAnalysisController({
		analysisId: "aid/finished",
		fetchFn: fetchSequence([
			jsonResponse(200, {status: "finished", verdict: "Safe"}),
			jsonResponse(200, [
				{seq: 1, timestamp: "t2", level: "warning", message: "second"},
				{seq: 0, timestamp: "t1", level: "info", message: "first"},
			]),
		], calls),
		EventSourceCtor: FakeEventSource,
		view,
	});

	await controller.load();

	assert.deepEqual(calls, [
		"/api/analyses/aid%2Ffinished",
		"/api/analyses/aid%2Ffinished/log",
	]);
	assert.deepEqual(view.entries.map((entry) => entry.seq), [0, 1]);
	assert.equal(view.verdict, "Safe");
	assert.deepEqual(view.statuses, ["loading", "finished"]);
	assert.deepEqual(
		view.actions.slice(-3),
		["check-tail", "verdict:Safe", "scroll-after-layout"],
	);
	assert.equal(FakeEventSource.instances.length, 0);
});

test("completed direct load reveals its stored TheHive case without a stream", async () => {
	FakeEventSource.instances = [];
	const view = createView();
	const controller = createAnalysisController({
		analysisId: "completed-case",
		fetchFn: fetchSequence([
			jsonResponse(200, {
				analysis_id: "completed-case",
				mail_uid: 9,
				status: "finished",
				created_at: "2026-07-29T10:00:00.000+00:00",
				started_at: "2026-07-29T10:00:01.000+00:00",
				finished_at: "2026-07-29T10:01:00.000+00:00",
				case_id: "~4628603072",
				case_number: "42",
				verdict: "Safe",
			}),
			jsonResponse(200, []),
		], []),
		EventSourceCtor: FakeEventSource,
		view,
	});

	await controller.load();

	assert.deepEqual(view.case, {caseId: "~4628603072", caseNumber: "42"});
	assert.equal(FakeEventSource.instances.length, 0);
});

test("running load follows SSE, de-duplicates replay, reconnects, and closes on terminal status", async () => {
	FakeEventSource.instances = [];
	const view = createView();
	const controller = createAnalysisController({
		analysisId: "aid1",
		fetchFn: fetchSequence([
			jsonResponse(200, {status: "running"}),
			jsonResponse(200, [
				{seq: 0, timestamp: "t1", level: "info", message: "stored"},
			]),
		], []),
		EventSourceCtor: FakeEventSource,
		view,
	});

	await controller.load();

	assert.equal(FakeEventSource.instances.length, 1);
	const source = FakeEventSource.instances[0];
	assert.equal(source.url, "/api/analyses/aid1/stream");
	source.emit("log", {seq: 0, timestamp: "t1", level: "info", message: "duplicate"});
	source.emit("log", {seq: 1, timestamp: "t2", level: "warning", message: "<b>live</b>"});
	assert.deepEqual(view.entries.map((entry) => entry.message), ["stored", "<b>live</b>"]);

	source.emit("error");
	assert.equal(view.connectionWarning, true);
	source.emit("open");
	assert.equal(view.connectionWarning, false);

	view.actions = [];
	source.emit("status", {type: "status", status: "finished", verdict: "Malicious"});
	assert.equal(source.closed, true);
	assert.equal(view.verdict, "Malicious");
	assert.equal(view.statuses.at(-1), "finished");
	assert.deepEqual(
		view.actions,
		["check-tail", "verdict:Malicious", "scroll-after-layout"],
	);
});

test("terminal status preserves a manually scrolled live log position", async () => {
	FakeEventSource.instances = [];
	const view = createView();
	const controller = createAnalysisController({
		analysisId: "manual-scroll",
		fetchFn: fetchSequence([
			jsonResponse(200, {status: "running"}),
			jsonResponse(200, []),
		], []),
		EventSourceCtor: FakeEventSource,
		view,
	});

	await controller.load();
	view.nearBottom = false;
	view.actions = [];
	FakeEventSource.instances[0].emit(
		"status",
		{type: "status", status: "finished", verdict: "Safe"},
	);

	assert.deepEqual(view.actions, ["check-tail", "verdict:Safe"]);
});

test("running analysis reveals live case data and preserves it at completion", async () => {
	FakeEventSource.instances = [];
	const view = createView();
	const controller = createAnalysisController({
		analysisId: "live-case",
		fetchFn: fetchSequence([
			jsonResponse(200, {
				analysis_id: "live-case",
				mail_uid: 9,
				status: "running",
				created_at: "2026-07-29T10:00:00.000+00:00",
				started_at: "2026-07-29T10:00:01.000+00:00",
			}),
			jsonResponse(200, []),
		], []),
		EventSourceCtor: FakeEventSource,
		view,
	});

	await controller.load();
	assert.equal(view.case, null);

	const source = FakeEventSource.instances[0];
	source.emit("status", {
		type: "status",
		status: "running",
		case_id: "~4628603072",
		case_number: "42",
	});
	assert.deepEqual(view.case, {caseId: "~4628603072", caseNumber: "42"});

	source.emit("status", {
		type: "status",
		status: "finished",
		verdict: "Suspicious",
	});
	assert.deepEqual(view.case, {caseId: "~4628603072", caseNumber: "42"});
	assert.equal(source.closed, true);
});

test("failed direct load shows persisted error and never opens a stream", async () => {
	FakeEventSource.instances = [];
	const view = createView();
	const controller = createAnalysisController({
		analysisId: "failed",
		fetchFn: fetchSequence([
			jsonResponse(200, {status: "failed", error: "Analyzer service failed"}),
			jsonResponse(200, []),
		], []),
		EventSourceCtor: FakeEventSource,
		view,
	});

	await controller.load();

	assert.equal(view.failure, "Analyzer service failed");
	assert.equal(view.statuses.at(-1), "failed");
	assert.equal(view.case, null);
	assert.deepEqual(
		view.actions.slice(-3),
		["check-tail", "failure", "scroll-after-layout"],
	);
	assert.equal(FakeEventSource.instances.length, 0);
});

test("failed direct load reveals a case created before the failure", async () => {
	FakeEventSource.instances = [];
	const view = createView();
	const controller = createAnalysisController({
		analysisId: "failed-with-case",
		fetchFn: fetchSequence([
			jsonResponse(200, {
				analysis_id: "failed-with-case",
				mail_uid: 9,
				status: "failed",
				created_at: "2026-07-29T10:00:00.000+00:00",
				started_at: "2026-07-29T10:00:01.000+00:00",
				finished_at: "2026-07-29T10:01:00.000+00:00",
				case_id: "~4628603072",
				case_number: "42",
				error: "Analyzer service failed",
			}),
			jsonResponse(200, []),
		], []),
		EventSourceCtor: FakeEventSource,
		view,
	});

	await controller.load();

	assert.deepEqual(view.case, {caseId: "~4628603072", caseNumber: "42"});
	assert.equal(view.failure, "Analyzer service failed");
	assert.equal(FakeEventSource.instances.length, 0);
});

test("initial API error shows its message and does not open a partial stream", async () => {
	FakeEventSource.instances = [];
	const view = createView();
	const controller = createAnalysisController({
		analysisId: "missing",
		fetchFn: fetchSequence([
			jsonResponse(404, {error: {message: "The analysis has expired."}}),
			jsonResponse(404, {error: {message: "The analysis has expired."}}),
		], []),
		EventSourceCtor: FakeEventSource,
		view,
	});

	await controller.load();

	assert.equal(view.alert, "The analysis has expired.");
	assert.equal(view.statuses.at(-1), "unavailable");
	assert.equal(FakeEventSource.instances.length, 0);
});

test("malformed log entries are rejected while valid text is preserved", () => {
	assert.equal(normalizeLogEntry({seq: -1, level: "info", message: "bad"}), null);
	assert.equal(normalizeLogEntry({seq: 1, level: "info"}), null);
	assert.deepEqual(
		normalizeLogEntry({seq: 2, timestamp: "now", level: "odd", message: "<script>"}),
		{seq: 2, timestamp: "now", level: "odd", message: "<script>"},
	);
});

test("TheHive case URL normalizes the base and encodes one path component", () => {
	assert.equal(
		buildTheHiveCaseUrl(" https://thehive.example.test/soc/// ", "~case/one"),
		"https://thehive.example.test/soc/cases/~case%2Fone/details",
	);
	assert.equal(
		buildTheHiveCaseUrl("https://thehive.example.test/soc", "~case1"),
		"https://thehive.example.test/soc/cases/~case1/details",
	);
	assert.equal(buildTheHiveCaseUrl("", "~case1"), null);
	assert.equal(buildTheHiveCaseUrl("https://thehive.example.test", "  "), null);
});

test("analysis view reveals and labels the exact TheHive case", () => {
	const {document, elements} = createAnalysisDocument({
		theHiveBaseUrl: "https://thehive.example.test/soc/",
	});
	const view = createAnalysisView(document);

	view.showCase("~case/one", " 42 ");

	assert.equal(
		elements.analysisCaseLink.attributes.href,
		"https://thehive.example.test/soc/cases/~case%2Fone/details",
	);
	assert.equal(elements.analysisCaseLinkText.textContent, "Open TheHive case #42");
	assert.equal(elements.analysisCaseLink.classList.contains("d-none"), false);
});

test("analysis view keeps the case action hidden when link data is incomplete", () => {
	const missingBase = createAnalysisDocument({theHiveBaseUrl: ""});
	createAnalysisView(missingBase.document).showCase("~case1", "42");
	assert.equal(missingBase.elements.analysisCaseLink.classList.contains("d-none"), true);

	const missingCase = createAnalysisDocument();
	createAnalysisView(missingCase.document).showCase("", "42");
	assert.equal(missingCase.elements.analysisCaseLink.classList.contains("d-none"), true);
});

test("analysis view uses a case-label fallback when the number is absent", () => {
	const {document, elements} = createAnalysisDocument();

	createAnalysisView(document).showCase("~case1", null);

	assert.equal(elements.analysisCaseLinkText.textContent, "Open TheHive case");
	assert.equal(elements.analysisCaseLink.classList.contains("d-none"), false);
});

test("analysis verdict messages do not infer configurable analysis actions", () => {
	const expectations = [
		["Safe", "The e-mail has been classified as SAFE. Review the analysis log or TheHive case for details."],
		["Suspicious", "The e-mail has been classified as SUSPICIOUS. Review the analysis log or TheHive case for details."],
		["Malicious", "The e-mail has been classified as MALICIOUS. Review the analysis log or TheHive case for details."],
	];

	for (const [verdict, expectedMessage] of expectations) {
		const {document, elements} = createAnalysisDocument();

		createAnalysisView(document).showVerdict(verdict);

		assert.equal(elements.analysisResultMessage.textContent, expectedMessage);
	}
});

test("analysis lifecycle reloads when a disposed page returns from BFCache", () => {
	const listeners = new Map();
	let disposed = 0;
	let reloads = 0;
	const fakeWindow = {
		addEventListener(name, listener) {
			listeners.set(name, listener);
		},
		location: {
			reload() {
				reloads += 1;
			},
		},
	};

	installAnalysisLifecycle(fakeWindow, {
		dispose() {
			disposed += 1;
		},
	});
	listeners.get("pagehide")();
	listeners.get("pageshow")({persisted: false});
	listeners.get("pageshow")({persisted: true});

	assert.equal(disposed, 1);
	assert.equal(reloads, 1);
});

test("analysis log view allowlists CSS levels and renders API text literally", () => {
	const {document, elements} = createAnalysisDocument();
	const view = createAnalysisView(document);
	const message = '<img src=x onerror="alert(1)">';

	for (const [seq, level] of ["info", "warning", "error"].entries()) {
		view.insertLogEntry({seq, level, message});
	}
	view.insertLogEntry({seq: 3, level: "unknown d-none", message});

	const lines = elements.analysisLogEntries.children;
	assert.deepEqual(
		lines.map((line) => line.className),
		[
			"analysis-log-line analysis-log-info",
			"analysis-log-line analysis-log-warning",
			"analysis-log-line analysis-log-error",
			"analysis-log-line analysis-log-neutral",
		],
	);
	assert.equal(lines[3].textContent, `[UNKNOWN D-NONE]: ${message}`);
	assert.equal(lines[3].children.length, 0);
});

test("analysis view defers terminal scrolling until the next layout frame", () => {
	const frames = [];
	const {document, elements} = createAnalysisDocument({
		requestAnimationFrame(callback) {
			frames.push(callback);
		},
	});
	const view = createAnalysisView(document);
	elements.analysisLog.scrollHeight = 720;
	elements.analysisLog.scrollTop = 120;

	view.scrollLogToBottomAfterLayout();

	assert.equal(elements.analysisLog.scrollTop, 120);
	assert.equal(frames.length, 1);
	frames.shift()();
	assert.equal(elements.analysisLog.scrollTop, 720);
});
