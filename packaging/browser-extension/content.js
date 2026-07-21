const indicator = document.createElement("div");
indicator.id = "mllminal-active-indicator";
indicator.textContent = "MLLminal active · draft-only";
Object.assign(indicator.style, {
  position: "fixed", top: "8px", right: "8px", zIndex: "2147483647",
  padding: "6px 9px", borderRadius: "6px", background: "#17324d",
  color: "#fff", font: "12px sans-serif", opacity: "0.92"
});
document.documentElement.appendChild(indicator);

function semanticControls() {
  return Array.from(document.querySelectorAll("button, input, textarea, [contenteditable='true']"))
    .map((element) => ({
      role: element.getAttribute("role") || element.tagName.toLowerCase(),
      label: element.getAttribute("aria-label") || element.getAttribute("name") || "",
      type: element.getAttribute("type") || ""
    }));
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "mllminal.inspect") {
    sendResponse({controls: semanticControls(), credentialsRead: false});
  }
});
