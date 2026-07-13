const form = document.querySelector("#inquiry-form");
const statusBox = document.querySelector("#form-status");
let pendingSubmissionId = null;

function newSubmissionId() {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = new Uint32Array(4);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (value) => value.toString(16)).join("-");
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button[type=submit]");
  const payload = Object.fromEntries(new FormData(form).entries());
  if (pendingSubmissionId === null) pendingSubmissionId = newSubmissionId();
  payload.submission_id = pendingSubmissionId;
  if (payload.guest_count_estimate === "") delete payload.guest_count_estimate;
  statusBox.className = "form-status";
  statusBox.textContent = "Testanfrage wird gespeichert …";
  button.disabled = true;
  try {
    const response = await fetch("/api/inquiries", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Speichern fehlgeschlagen.");
    statusBox.className = "form-status success";
    const destination = result.forwarded_to_core ? "In Core übernommen." : "Nur im Staging gespeichert.";
    statusBox.textContent = `Gespeichert — Test-ID ${result.submission_id.slice(-8)}. ${destination}`;
    pendingSubmissionId = null;
    form.reset();
  } catch (error) {
    statusBox.className = "form-status error";
    statusBox.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
