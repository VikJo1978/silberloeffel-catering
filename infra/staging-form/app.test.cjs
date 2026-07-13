const assert = require("node:assert/strict");
const test = require("node:test");

const {
  CONTACT_ERROR,
  REQUEST_TIMEOUT_MS,
  hasContact,
  requestFailureMessage,
  responseErrorMessage,
} = require("../../src/catering_system/ui/staging_site_assets/app.js");

test("contact validation accepts either non-blank channel", () => {
  assert.equal(hasContact({ email: "kunde@example.test", phone: "" }), true);
  assert.equal(hasContact({ email: "", phone: "040 123" }), true);
  assert.equal(hasContact({ email: "  ", phone: "\t" }), false);
  assert.equal(CONTACT_ERROR, "Bitte mindestens E-Mail oder Telefon angeben.");
});

test("known HTTP failures have stable German messages", () => {
  assert.match(responseErrorMessage(400), /Angaben/);
  assert.match(responseErrorMessage(413), /umfangreich/);
  assert.match(responseErrorMessage(429), /Minute/);
  assert.match(responseErrorMessage(502), /Core/);
  assert.match(responseErrorMessage(500), /später/);
});

test("network and timeout failures do not expose technical parser text", () => {
  const timeout = new Error("technical abort detail");
  timeout.name = "AbortError";
  assert.match(requestFailureMessage(timeout), /dauert zu lange/);
  assert.doesNotMatch(requestFailureMessage(timeout), /technical/);

  const network = new TypeError("Failed to fetch internal detail");
  assert.match(requestFailureMessage(network), /Server/);
  assert.doesNotMatch(requestFailureMessage(network), /internal/);
  assert.equal(REQUEST_TIMEOUT_MS, 12000);
});
