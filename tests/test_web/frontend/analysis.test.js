"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
	createAnalysisController,
	normalizeLogEntry,
} = require("../../../app/web/static/assets/js/analysis.js");

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
		alert: null,
		connectionWarning: false,
		entries: [],
		failure: null,
		statuses: [],
		verdict: null,
		clearAlert() {
			this.alert = null;
		},
		setStatus(status) {
			this.statuses.push(status);
		},
		insertLogEntry(entry) {
			this.entries.push(entry);
			this.entries.sort((left, right) => left.seq - right.seq);
		},
		isLogNearBottom() {
			return true;
		},
		scrollLogToBottom() {},
		showVerdict(verdict) {
			this.verdict = verdict;
		},
		showFailure(message) {
			this.failure = message;
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

	source.emit("status", {type: "status", status: "finished", verdict: "Malicious"});
	assert.equal(source.closed, true);
	assert.equal(view.verdict, "Malicious");
	assert.equal(view.statuses.at(-1), "finished");
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
