import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(
  new URL(
    "../../src/catering_system/ui/office_panel_tasks_list.py",
    import.meta.url,
  ),
  "utf8",
);

const shellSource = readFileSync(
  new URL(
    "../../src/catering_system/ui/office_panel_shell.py",
    import.meta.url,
  ),
  "utf8",
);

const marker = '_SUBJECT_PICKER_SCRIPT = r"""';
const start = source.indexOf(marker);
assert.notEqual(start, -1, "subject picker script marker must exist");
const scriptStart = start + marker.length;
const scriptEnd = source.indexOf('\n"""', scriptStart);
assert.notEqual(scriptEnd, -1, "subject picker script terminator must exist");

const embeddedScript = source
  .slice(scriptStart, scriptEnd)
  .trim()
  .replace(/^<script>\s*/, "")
  .replace(/\s*<\/script>$/, "");

class FakeElement {
  constructor({ dataset = {}, hidden = false } = {}) {
    this.dataset = { ...dataset };
    this.hidden = hidden;
    this.value = "";
    this.textContent = "";
    this.open = false;
    this.focused = false;
    this.attributes = new Map();
    this.listeners = new Map();
  }

  addEventListener(type, listener) {
    this.listeners.set(type, listener);
  }

  dispatch(type) {
    const listener = this.listeners.get(type);
    if (listener) listener();
  }

  click() {
    this.dispatch("click");
  }

  focus() {
    this.focused = true;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.get(name);
  }
}

function buildFixture() {
  const picker = new FakeElement();
  const search = new FakeElement();
  const hidden = new FakeElement();
  const selection = new FakeElement();
  const summarySelection = new FakeElement();
  const results = new FakeElement({ hidden: true });
  const empty = new FakeElement({ hidden: true });

  const categories = ["NONE", "CONTACT", "INQUIRY", "OFFER", "ORDER"].map(
    (category) =>
      new FakeElement({
        dataset: { subjectCategoryFilter: category },
      }),
  );

  const resultButtons = [
    new FakeElement({
      hidden: true,
      dataset: {
        subjectCategory: "OFFER",
        subjectValue: "OFFER:offer-muster",
        subjectLabel: "Angebot · Musterfirma Hamburg · 2026-08-15",
        subjectSearch: "Angebot · Musterfirma Hamburg · 2026-08-15",
      },
    }),
    new FakeElement({
      hidden: true,
      dataset: {
        subjectCategory: "OFFER",
        subjectValue: "OFFER:offer-frost",
        subjectLabel: "Angebot · Frost UG · 2026-09-01",
        subjectSearch: "Angebot · Frost UG · 2026-09-01",
      },
    }),
    new FakeElement({
      hidden: true,
      dataset: {
        subjectCategory: "CONTACT",
        subjectValue: "CONTACT:kontakt-muster",
        subjectLabel: "Kontakt · Musterfirma Hamburg",
        subjectSearch: "Kontakt · Musterfirma Hamburg",
      },
    }),
  ];

  picker.querySelectorAll = (selector) => {
    if (selector === "[data-subject-category-filter]") return categories;
    if (selector === "[data-subject-result]") return resultButtons;
    return [];
  };

  const byId = new Map([
    ["manual_task_subject_picker", picker],
    ["manual_task_subject_search", search],
    ["manual_task_subject", hidden],
    ["manual_task_subject_selection", selection],
    ["manual_task_subject_summary_selection", summarySelection],
    ["manual_task_subject_results", results],
    ["manual_task_subject_empty", empty],
  ]);

  const document = {
    getElementById(id) {
      return byId.get(id) ?? null;
    },
  };

  vm.runInNewContext(embeddedScript, { document });

  return {
    picker,
    search,
    hidden,
    selection,
    summarySelection,
    results,
    empty,
    categories,
    resultButtons,
  };
}

test("picker starts compact without dumping all subjects", () => {
  const fixture = buildFixture();

  assert.equal(fixture.picker.open, false);
  assert.equal(fixture.results.hidden, true);
  assert.equal(fixture.empty.hidden, true);
  assert.ok(fixture.resultButtons.every((button) => button.hidden));
});

test("category click reveals only that category and search narrows it", () => {
  const fixture = buildFixture();
  const offerCategory = fixture.categories.find(
    (button) => button.dataset.subjectCategoryFilter === "OFFER",
  );

  offerCategory.click();

  assert.equal(offerCategory.getAttribute("aria-pressed"), "true");
  assert.equal(fixture.results.hidden, false);
  assert.equal(fixture.resultButtons[0].hidden, false);
  assert.equal(fixture.resultButtons[1].hidden, false);
  assert.equal(fixture.resultButtons[2].hidden, true);
  assert.equal(fixture.search.focused, true);

  fixture.search.value = "muster";
  fixture.search.dispatch("input");

  assert.equal(fixture.resultButtons[0].hidden, false);
  assert.equal(fixture.resultButtons[1].hidden, true);
  assert.equal(fixture.resultButtons[2].hidden, true);
});

test("search without category searches across all subject types", () => {
  const fixture = buildFixture();

  fixture.search.value = "musterfirma";
  fixture.search.dispatch("input");

  assert.equal(fixture.results.hidden, false);
  assert.equal(fixture.resultButtons[0].hidden, false);
  assert.equal(fixture.resultButtons[1].hidden, true);
  assert.equal(fixture.resultButtons[2].hidden, false);
});

test("result selection writes the existing subject_reference contract", () => {
  const fixture = buildFixture();
  fixture.picker.open = true;

  fixture.resultButtons[0].click();

  assert.equal(fixture.hidden.value, "OFFER:offer-muster");
  assert.equal(
    fixture.selection.textContent,
    "Angebot · Musterfirma Hamburg · 2026-08-15",
  );
  assert.equal(
    fixture.summarySelection.textContent,
    "Angebot · Musterfirma Hamburg · 2026-08-15",
  );
  assert.equal(fixture.picker.open, false);
});

test("Ohne Bezug clears selection and collapses the picker", () => {
  const fixture = buildFixture();
  const noneCategory = fixture.categories.find(
    (button) => button.dataset.subjectCategoryFilter === "NONE",
  );

  fixture.hidden.value = "OFFER:offer-muster";
  fixture.search.value = "muster";
  fixture.picker.open = true;
  noneCategory.click();

  assert.equal(fixture.hidden.value, "");
  assert.equal(fixture.search.value, "");
  assert.equal(fixture.selection.textContent, "Ohne Bezug");
  assert.equal(fixture.summarySelection.textContent, "Ohne Bezug");
  assert.equal(fixture.results.hidden, true);
  assert.equal(fixture.picker.open, false);
});

test("hidden picker rows remain hidden under author display rules", () => {
  assert.match(
    shellSource,
    /\.task-subject-result\[hidden\][\s\S]*display:\s*none\s*!important;/,
  );
});
