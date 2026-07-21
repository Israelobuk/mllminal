const BLOCKED_PATHS = ["/login", "/signin", "/signup", "/checkout", "/payment", "/security", "/account/recovery"];

function isBlocked(url) {
  const path = new URL(url).pathname.toLowerCase();
  return BLOCKED_PATHS.some((fragment) => path.includes(fragment));
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== "mllminal.prepare") return false;
  if (!sender.tab?.url || isBlocked(sender.tab.url)) {
    sendResponse({ok: false, error: "blocked_security_or_payment_surface"});
    return false;
  }
  if (!message.domain || !Array.isArray(message.operations)) {
    sendResponse({ok: false, error: "invalid_semantic_request"});
    return false;
  }
  chrome.storage.local.get([`permission:${message.domain}`], (value) => {
    const granted = value[`permission:${message.domain}`] === true;
    if (!granted) {
      sendResponse({ok: false, error: "domain_permission_required"});
      return;
    }
    sendResponse({ok: true, sent: false, credentialsRead: false, visibleIndicator: "mllminal-active"});
  });
  return true;
});
