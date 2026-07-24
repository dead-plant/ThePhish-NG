"use strict";

class FakeClassList {
	constructor(element) {
		this.element = element;
	}

	tokens() {
		return this.element.className.split(/\s+/).filter(Boolean);
	}

	add(...tokens) {
		this.element.className = [...new Set([...this.tokens(), ...tokens])].join(" ");
	}

	remove(...tokens) {
		const removed = new Set(tokens);
		this.element.className = this.tokens()
			.filter((token) => !removed.has(token))
			.join(" ");
	}

	contains(token) {
		return this.tokens().includes(token);
	}
}

class FakeElement {
	constructor(tagName = "div") {
		this.tagName = tagName.toUpperCase();
		this.children = [];
		this.parentNode = null;
		this.attributes = {};
		this.className = "";
		this.classList = new FakeClassList(this);
		this.dataset = {};
		this.disabled = false;
		this.listeners = new Map();
		this.scrollHeight = 0;
		this.scrollTop = 0;
		this.clientHeight = 0;
		this.style = {cssText: ""};
		this.type = "";
		this._textContent = "";
	}

	get firstElementChild() {
		return this.children[0] || null;
	}

	get rows() {
		return this.children.filter((child) => child.tagName === "TR");
	}

	get textContent() {
		if (this.children.length > 0) {
			return this.children.map((child) => child.textContent).join("");
		}
		return this._textContent;
	}

	set textContent(value) {
		this._textContent = String(value);
		this.children = [];
	}

	appendChild(child) {
		child.parentNode = this;
		this.children.push(child);
		return child;
	}

	insertBefore(child, reference) {
		child.parentNode = this;
		if (reference === null) {
			this.children.push(child);
			return child;
		}
		const index = this.children.indexOf(reference);
		if (index === -1) {
			throw new Error("Reference node is not a child");
		}
		this.children.splice(index, 0, child);
		return child;
	}

	remove() {
		if (!this.parentNode) {
			return;
		}
		this.parentNode.children = this.parentNode.children
			.filter((child) => child !== this);
		this.parentNode = null;
	}

	setAttribute(name, value) {
		this.attributes[name] = String(value);
	}

	addEventListener(name, listener) {
		if (!this.listeners.has(name)) {
			this.listeners.set(name, []);
		}
		this.listeners.get(name).push(listener);
	}

	querySelector(selector) {
		return this.querySelectorAll(selector)[0] || null;
	}

	querySelectorAll(selector) {
		if (!selector.startsWith(".")) {
			throw new Error(`Unsupported selector: ${selector}`);
		}
		const className = selector.slice(1);
		const matches = [];
		for (const child of this.children) {
			if (child.classList.contains(className)) {
				matches.push(child);
			}
			matches.push(...child.querySelectorAll(selector));
		}
		return matches;
	}
}

class FakeDocument {
	constructor(elements = {}, defaultView = null) {
		this.defaultView = defaultView;
		this.elements = elements;
	}

	getElementById(id) {
		return this.elements[id] || null;
	}

	createElement(tagName) {
		return new FakeElement(tagName);
	}
}

function createAnalysisDocument({requestAnimationFrame} = {}) {
	const elements = {
		analysisStatus: new FakeElement(),
		analysisAlert: new FakeElement(),
		analysisLog: new FakeElement(),
		analysisLogEntries: new FakeElement(),
		analysisResult: new FakeElement(),
		analysisResultTitle: new FakeElement(),
		analysisResultMessage: new FakeElement(),
	};
	const defaultView = requestAnimationFrame ? {requestAnimationFrame} : null;
	return {
		document: new FakeDocument(elements, defaultView),
		elements,
	};
}

function createIndexDocument() {
	const progress = new FakeElement();
	progress.appendChild(new FakeElement());

	const tableBody = new FakeElement("tbody");
	const table = new FakeElement("table");
	table.tBodies = [tableBody];
	table.appendChild(tableBody);

	const elements = {
		descDiv: new FakeElement(),
		divDataTable: new FakeElement(),
		dataTable: table,
		listMailsBtn: new FakeElement("button"),
		progressBar: progress,
		cardHeader: new FakeElement(),
	};
	return {
		document: new FakeDocument(elements),
		elements,
		tableBody,
	};
}

module.exports = {
	createAnalysisDocument,
	createIndexDocument,
	FakeElement,
};
