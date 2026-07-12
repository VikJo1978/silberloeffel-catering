const form = document.querySelector("#inquiry-form");
const statusBox = document.querySelector("#form-status");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button[type=submit]");
  const payload = Object.fromEntries(new FormData(form).entries());
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
    statusBox.textContent = `Gespeichert — Test-ID ${result.submission_id.slice(0, 8)}. Keine Weiterleitung an Production.`;
    form.reset();
  } catch (error) {
    statusBox.className = "form-status error";
    statusBox.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
