"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
	createIndexController,
} = require("../../../app/web/static/assets/js/thephish.js");

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
		emails: null,
		listingLoading: false,
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
			this.onAnalyze = onAnalyze;
		},
		beginAnalysis() {
			this.analysisLoading = true;
		},
		endAnalysis() {
			this.analysisLoading = false;
		},
	};
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
