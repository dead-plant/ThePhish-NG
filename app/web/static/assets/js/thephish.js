(function(root, factory) {
	"use strict";
	const api = factory();
	if (typeof module === "object" && module.exports) {
		module.exports = api;
	}
	if (root) {
		root.ThePhishIndex = api;
	}
})(typeof window !== "undefined" ? window : null, function() {
	"use strict";

	const listFallback = "An unexpected error occurred while listing emails. Please try again later.";
	const analysisFallback = "The analysis could not be started. Please try again later.";

	class DisplayError extends Error {}

	async function readJson(response, fallbackMessage, expectedStatus) {
		let body;
		try {
			body = await response.json();
		} catch (_error) {
			throw new DisplayError(fallbackMessage);
		}
		if (!response.ok || (expectedStatus !== undefined && response.status !== expectedStatus)) {
			const message = body && body.error && typeof body.error.message === "string"
				? body.error.message
				: fallbackMessage;
			throw new DisplayError(message);
		}
		return body;
	}

	function normalizeMailUid(value) {
		const uid = typeof value === "string" && /^\d+$/.test(value.trim())
			? Number(value.trim())
			: value;
		return Number.isSafeInteger(uid) && uid > 0 ? uid : null;
	}

	function createIndexController({fetchFn, navigate, view}) {
		let disposed = false;
		let generation = 0;

		function beginOperation() {
			if (disposed) {
				return null;
			}
			generation += 1;
			return generation;
		}

		function isCurrent(operation) {
			return !disposed && operation === generation;
		}

		async function listEmails() {
			const operation = beginOperation();
			if (operation === null) {
				return;
			}
			view.clearAlert();
			view.beginListing();
			try {
				const response = await fetchFn("/api/emails");
				if (!isCurrent(operation)) {
					return;
				}
				const emails = await readJson(response, listFallback);
				if (!isCurrent(operation)) {
					return;
				}
				if (!Array.isArray(emails)) {
					throw new DisplayError(listFallback);
				}
				view.renderEmails(emails, startAnalysis);
				if (emails.length === 0) {
					view.showAlert("warning", "There are no emails to read.");
				}
			} catch (error) {
				if (!isCurrent(operation)) {
					return;
				}
				view.renderEmails([], startAnalysis);
				view.showAlert(
					"error",
					error instanceof DisplayError ? error.message : listFallback,
				);
			} finally {
				if (isCurrent(operation)) {
					view.endListing();
				}
			}
		}

		async function startAnalysis(mailUid) {
			const operation = beginOperation();
			if (operation === null) {
				return;
			}
			view.clearAlert();
			const normalizedUid = normalizeMailUid(mailUid);
			if (normalizedUid === null) {
				view.showAlert("error", analysisFallback);
				return;
			}

			view.beginAnalysis();
			try {
				const response = await fetchFn("/api/analyses", {
					method: "POST",
					headers: {"Content-Type": "application/json"},
					body: JSON.stringify({mail_uid: normalizedUid}),
				});
				if (!isCurrent(operation)) {
					return;
				}
				const state = await readJson(response, analysisFallback, 202);
				if (!isCurrent(operation)) {
					return;
				}
				if (!state || typeof state.analysis_id !== "string" || !state.analysis_id.trim()) {
					throw new DisplayError(analysisFallback);
				}
				navigate(`/analysis/${encodeURIComponent(state.analysis_id)}`);
			} catch (error) {
				if (!isCurrent(operation)) {
					return;
				}
				view.endAnalysis();
				view.showAlert(
					"error",
					error instanceof DisplayError ? error.message : analysisFallback,
				);
			}
		}

		function dispose() {
			disposed = true;
			generation += 1;
		}

		return {listEmails, startAnalysis, dispose};
	}

	function createIndexView(document) {
		const description = document.getElementById("descDiv");
		const tableWrapper = document.getElementById("divDataTable");
		const table = document.getElementById("dataTable");
		const listButton = document.getElementById("listMailsBtn");
		const progress = document.getElementById("progressBar");
		const progressFill = progress.firstElementChild;
		const cardHeader = document.getElementById("cardHeader");

		function clearAlert() {
			const alert = cardHeader.querySelector(".operation-alert");
			if (alert) {
				alert.remove();
			}
		}

		function showAlert(type, message) {
			clearAlert();
			const alert = document.createElement("div");
			alert.className = `operation-alert alert alert-${type === "warning" ? "warning" : "danger"} alert-dismissible`;
			alert.setAttribute("role", "alert");
			alert.style.cssText = "text-align: left;margin-top: 15px;margin-bottom: 0px;";

			const close = document.createElement("button");
			close.type = "button";
			close.className = "btn-close";
			close.setAttribute("data-bs-dismiss", "alert");
			close.setAttribute("aria-label", "Close");
			alert.appendChild(close);

			const strong = document.createElement("strong");
			strong.textContent = message;
			alert.appendChild(strong);
			cardHeader.appendChild(alert);
		}

		function showProgress(message) {
			progress.classList.remove("d-none");
			progressFill.classList.add("bg-info", "progress-bar-animated");
			progressFill.classList.remove("bg-danger", "bg-success");
			progressFill.textContent = message;
		}

		function hideProgress() {
			progress.classList.add("d-none");
			progressFill.classList.remove("progress-bar-animated");
			progressFill.textContent = "";
		}

		function beginListing() {
			table.tBodies[0].textContent = "";
			tableWrapper.classList.add("d-none");
			listButton.disabled = true;
			listButton.classList.add("d-none");
			showProgress("Retrieving emails…");
		}

		function endListing() {
			listButton.disabled = false;
			listButton.classList.remove("d-none");
			hideProgress();
		}

		function renderEmails(emails, onAnalyze) {
			table.tBodies[0].textContent = "";
			if (emails.length === 0) {
				tableWrapper.classList.add("d-none");
				return;
			}
			for (const email of emails) {
				const row = document.createElement("tr");
				for (const field of ["uid", "date", "sender", "subject", "body", "attached_subject"]) {
					const cell = document.createElement("td");
					cell.textContent = email[field] == null ? "" : String(email[field]);
					row.appendChild(cell);
				}
				const actionCell = document.createElement("td");
				actionCell.className = "justify-content-xl-end";
				const button = document.createElement("button");
				button.className = "btn btn-primary border rounded analyze-email-btn";
				button.type = "button";
				button.style.cssText = "background: rgb(40,106,149);font-size: 20px;";
				button.textContent = "Analyze";
				button.addEventListener("click", () => onAnalyze(email.uid));
				actionCell.appendChild(button);
				row.appendChild(actionCell);
				table.tBodies[0].appendChild(row);
			}
			description.classList.add("d-none");
			tableWrapper.classList.remove("d-none");
		}

		function beginAnalysis() {
			listButton.disabled = true;
			listButton.classList.add("d-none");
			tableWrapper.classList.add("d-none");
			for (const button of table.querySelectorAll(".analyze-email-btn")) {
				button.disabled = true;
			}
			showProgress("Starting analysis…");
		}

		function endAnalysis() {
			listButton.disabled = false;
			listButton.classList.remove("d-none");
			if (table.tBodies[0].rows.length > 0) {
				tableWrapper.classList.remove("d-none");
			}
			for (const button of table.querySelectorAll(".analyze-email-btn")) {
				button.disabled = false;
			}
			hideProgress();
		}

		return {
			clearAlert,
			showAlert,
			beginListing,
			endListing,
			renderEmails,
			beginAnalysis,
			endAnalysis,
		};
	}

	function installIndexLifecycle(window, controller) {
		window.addEventListener("pagehide", () => controller.dispose());
		window.addEventListener("pageshow", (event) => {
			if (event.persisted) {
				window.location.reload();
			}
		});
	}

	function boot(window) {
		const view = createIndexView(window.document);
		const controller = createIndexController({
			fetchFn: window.fetch.bind(window),
			navigate: (destination) => window.location.assign(destination),
			view,
		});
		window.document.getElementById("listMailsBtn")
			.addEventListener("click", controller.listEmails);
		installIndexLifecycle(window, controller);
	}

	if (typeof window !== "undefined" && window.document) {
		window.document.addEventListener("DOMContentLoaded", () => boot(window));
	}

	return {
		createIndexController,
		createIndexView,
		installIndexLifecycle,
		normalizeMailUid,
	};
});
