"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
	createIndexController,
	createIndexView,
	installIndexLifecycle,
} = require("../../../app/web/static/assets/js/thephish.js");
const {
	createIndexDocument,
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

function createView() {
	return {
		alerts: [],
		analysisLoading: false,
		analysisEndCount: 0,
		emails: null,
		listingLoading: false,
		renderedEmails: [],
		clearAlert() {},
		showAlert(type, message) {
			this.alerts.push({type, message});
		},
		beginListing() {
			this.listingLoading = true;
		},
		endListing() {
			this.listingLoading = false;
		},
		renderEmails(emails, onAnalyze) {
			this.emails = emails;
			this.renderedEmails.push(emails);
			this.onAnalyze = onAnalyze;
		},
		beginAnalysis() {
			this.analysisLoading = true;
		},
		endAnalysis() {
			this.analysisLoading = false;
			this.analysisEndCount += 1;
		},
	};
}

function deferred() {
	let resolve;
	const promise = new Promise((promiseResolve) => {
		resolve = promiseResolve;
	});
	return {promise, resolve};
}

test("listEmails fetches and renders the current email array", async () => {
	const calls = [];
	const view = createView();
	const controller = createIndexController({
		fetchFn: async (...args) => {
			calls.push(args);
			return jsonResponse(200, [{uid: 7, subject: "Report"}]);
		},
		navigate() {},
		view,
	});

	await controller.listEmails();

	assert.deepEqual(calls, [["/api/emails"]]);
	assert.deepEqual(view.emails, [{uid: 7, subject: "Report"}]);
	assert.equal(view.listingLoading, false);
	assert.deepEqual(view.alerts, []);
});

test("listEmails reports empty and failed results without losing controls", async () => {
	const emptyView = createView();
	const emptyController = createIndexController({
		fetchFn: async () => jsonResponse(200, []),
		navigate() {},
		view: emptyView,
	});
	await emptyController.listEmails();
	assert.deepEqual(emptyView.alerts, [
		{type: "warning", message: "There are no emails to read."},
	]);
	assert.equal(emptyView.listingLoading, false);

	const failedView = createView();
	const failedController = createIndexController({
		fetchFn: async () => jsonResponse(503, {
			success: false,
			error: {code: "imap_connection_failed", message: "Mailbox unavailable."},
		}),
		navigate() {},
		view: failedView,
	});
	await failedController.listEmails();
	assert.deepEqual(failedView.alerts, [
		{type: "error", message: "Mailbox unavailable."},
	]);
	assert.equal(failedView.listingLoading, false);

	const networkView = createView();
	const networkController = createIndexController({
		fetchFn: async () => {
			throw new Error("network down");
		},
		navigate() {},
		view: networkView,
	});
	await networkController.listEmails();
	assert.deepEqual(networkView.alerts, [
		{type: "error", message: "An unexpected error occurred while listing emails. Please try again later."},
	]);
	assert.equal(networkView.listingLoading, false);
});

test("startAnalysis posts JSON and redirects to the encoded analysis page", async () => {
	const calls = [];
	const destinations = [];
	const view = createView();
	const controller = createIndexController({
		fetchFn: async (...args) => {
			calls.push(args);
			return jsonResponse(202, {analysis_id: "aid with space", status: "pending"});
		},
		navigate(destination) {
			destinations.push(destination);
		},
		view,
	});

	await controller.startAnalysis("42");

	assert.equal(calls.length, 1);
	assert.equal(calls[0][0], "/api/analyses");
	assert.equal(calls[0][1].method, "POST");
	assert.equal(calls[0][1].headers["Content-Type"], "application/json");
	assert.equal(calls[0][1].body, JSON.stringify({mail_uid: 42}));
	assert.deepEqual(destinations, ["/analysis/aid%20with%20space"]);
	assert.equal(view.analysisLoading, true);
});

test("startAnalysis restores the index and displays API or fallback errors", async () => {
	const apiView = createView();
	const apiController = createIndexController({
		fetchFn: async () => jsonResponse(503, {
			error: {message: "The analysis backend is unavailable."},
		}),
		navigate() {},
		view: apiView,
	});
	await apiController.startAnalysis(5);
	assert.equal(apiView.analysisLoading, false);
	assert.deepEqual(apiView.alerts, [
		{type: "error", message: "The analysis backend is unavailable."},
	]);

	const malformedView = createView();
	const malformedController = createIndexController({
		fetchFn: async () => jsonResponse(202, {status: "pending"}),
		navigate() {},
		view: malformedView,
	});
	await malformedController.startAnalysis(5);
	assert.equal(malformedView.analysisLoading, false);
	assert.deepEqual(malformedView.alerts, [
		{type: "error", message: "The analysis could not be started. Please try again later."},
	]);

	const networkView = createView();
	const networkController = createIndexController({
		fetchFn: async () => {
			throw new Error("network down");
		},
		navigate() {},
		view: networkView,
	});
	await networkController.startAnalysis(5);
	assert.equal(networkView.analysisLoading, false);
	assert.deepEqual(networkView.alerts, [
		{type: "error", message: "The analysis could not be started. Please try again later."},
	]);
});

test("a superseded email request cannot overwrite the current listing state", async () => {
	const firstResponse = deferred();
	const secondResponse = deferred();
	const responses = [firstResponse.promise, secondResponse.promise];
	const view = createView();
	const controller = createIndexController({
		fetchFn: async () => responses.shift(),
		navigate() {},
		view,
	});

	const firstRequest = controller.listEmails();
	const secondRequest = controller.listEmails();
	firstResponse.resolve(jsonResponse(200, [{uid: 1, subject: "stale"}]));
	await firstRequest;

	assert.deepEqual(view.renderedEmails, []);
	assert.equal(view.listingLoading, true);

	secondResponse.resolve(jsonResponse(200, [{uid: 2, subject: "current"}]));
	await secondRequest;

	assert.deepEqual(view.emails, [{uid: 2, subject: "current"}]);
	assert.equal(view.listingLoading, false);
});

test("disposing the index suppresses a pending analysis completion", async () => {
	const response = deferred();
	const destinations = [];
	const view = createView();
	const controller = createIndexController({
		fetchFn: async () => response.promise,
		navigate(destination) {
			destinations.push(destination);
		},
		view,
	});

	const pending = controller.startAnalysis(42);
	controller.dispose();
	response.resolve(jsonResponse(202, {analysis_id: "late", status: "pending"}));
	await pending;

	assert.deepEqual(destinations, []);
	assert.equal(view.analysisEndCount, 0);
	assert.deepEqual(view.alerts, []);
});

test("index lifecycle disposes on pagehide and reloads a persisted page", () => {
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

	installIndexLifecycle(fakeWindow, {
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

test("index DOM adapter renders API text literally in cells and alerts", () => {
	const {document, elements, tableBody} = createIndexDocument();
	const view = createIndexView(document);
	const markup = '<img src=x onerror="alert(1)">';

	view.renderEmails([{
		uid: 7,
		date: "today",
		sender: markup,
		subject: "<script>subject</script>",
		body: "<b>body</b>",
		attached_subject: "<i>attachment</i>",
	}], () => {});
	view.showAlert("error", markup);

	const row = tableBody.rows[0];
	assert.equal(row.children[2].textContent, markup);
	assert.equal(row.children[2].children.length, 0);
	assert.equal(row.children[3].textContent, "<script>subject</script>");
	const alert = elements.cardHeader.querySelector(".operation-alert");
	const strong = alert.children[1];
	assert.equal(strong.textContent, markup);
	assert.equal(strong.children.length, 0);
});
