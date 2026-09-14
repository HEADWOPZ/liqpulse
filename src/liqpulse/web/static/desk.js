const btn = document.getElementById("refresh");
const status = document.getElementById("status");

if (btn) {
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    status.textContent = "ingesting…";
    try {
      const res = await fetch("/api/ingest", { method: "POST" });
      const data = await res.json();
      status.textContent = `ok ${data.snapshots} snaps / ${data.cards} cards`;
      window.location.reload();
    } catch (err) {
      status.textContent = "ingest failed";
      btn.disabled = false;
    }
  });
}
