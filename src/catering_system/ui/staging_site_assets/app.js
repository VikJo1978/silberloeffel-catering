const REQUEST_TIMEOUT_MS = 12000;
const CONTACT_ERROR = "Bitte mindestens E-Mail oder Telefon angeben.";

function hasContact(payload) {
  return [payload.email, payload.phone].some(
    (value) => typeof value === "string" && value.trim() !== "",
  );
}

function responseErrorMessage(status) {
  const messages = {
    400: "Bitte prüfen Sie Ihre Angaben und versuchen Sie es erneut.",
    413: "Die Anfrage ist zu umfangreich. Bitte kürzen Sie den Wunschtext.",
    415: "Die Anfrage konnte technisch nicht verarbeitet werden.",
    429: "Zu viele Versuche. Bitte warten Sie eine Minute und senden Sie erneut.",
    502: "Core ist vorübergehend nicht erreichbar. Bitte senden Sie später erneut; Ihre Angaben bleiben im Formular.",
  };
  return messages[status] || "Speichern derzeit nicht möglich. Bitte versuchen Sie es später erneut.";
}

function requestFailureMessage(error) {
  if (error && error.name === "AbortError") {
    return "Die Übertragung dauert zu lange. Bitte prüfen Sie die Verbindung und senden Sie erneut.";
  }
  if (error instanceof TypeError) {
    return "Der Server ist momentan nicht erreichbar. Bitte senden Sie später erneut; Ihre Angaben bleiben im Formular.";
  }
  return error instanceof Error
    ? error.message
    : "Speichern derzeit nicht möglich. Bitte versuchen Sie es später erneut.";
}

function newSubmissionId() {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = new Uint32Array(4);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (value) => value.toString(16)).join("-");
}

if (typeof document !== "undefined") {
  const form = document.querySelector("#inquiry-form");
  const statusBox = document.querySelector("#form-status");
  const emailInput = form.querySelector("[name=email]");
  const phoneInput = form.querySelector("[name=phone]");
  let pendingSubmissionId = null;

  function clearContactError() {
    emailInput.setCustomValidity("");
    phoneInput.setCustomValidity("");
  }

  emailInput.addEventListener("input", clearContactError);
  phoneInput.addEventListener("input", clearContactError);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button[type=submit]");
    const payload = Object.fromEntries(new FormData(form).entries());
    clearContactError();
    if (!hasContact(payload)) {
      emailInput.setCustomValidity(CONTACT_ERROR);
      statusBox.className = "form-status error";
      statusBox.textContent = CONTACT_ERROR;
      emailInput.focus();
      return;
    }

    if (pendingSubmissionId === null) pendingSubmissionId = newSubmissionId();
    payload.submission_id = pendingSubmissionId;
    if (payload.guest_count_estimate === "") delete payload.guest_count_estimate;
    statusBox.className = "form-status";
    statusBox.textContent = "Testanfrage wird gespeichert …";
    form.setAttribute("aria-busy", "true");
    button.disabled = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch("/api/inquiries", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      let result = null;
      try {
        result = await response.json();
      } catch {
        // Reverse proxies can return HTML on failure. Never show parser details.
      }
      if (!response.ok) throw new Error(responseErrorMessage(response.status));
      if (
        !result ||
        result.accepted !== true ||
        typeof result.submission_id !== "string"
      ) {
        throw new Error("Der Server hat keine gültige Bestätigung gesendet. Bitte erneut versuchen.");
      }
      statusBox.className = "form-status success";
      const destination = result.forwarded_to_core
        ? "In Core übernommen."
        : "Nur im Staging gespeichert.";
      statusBox.textContent = `Gespeichert — Test-ID ${result.submission_id.slice(-8)}. ${destination}`;
      pendingSubmissionId = null;
      form.reset();
    } catch (error) {
      statusBox.className = "form-status error";
      statusBox.textContent = requestFailureMessage(error);
    } finally {
      clearTimeout(timeout);
      form.removeAttribute("aria-busy");
      button.disabled = false;
    }
  });
}

if (typeof module !== "undefined") {
  module.exports = {
    CONTACT_ERROR,
    REQUEST_TIMEOUT_MS,
    hasContact,
    requestFailureMessage,
    responseErrorMessage,
  };
}
