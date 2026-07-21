# MLLminal browser bridge

This unpacked Manifest V3 extension is the primary portable path for signed-in
Gmail, Outlook Web, and browser spreadsheet surfaces. It exposes semantic DOM
controls, requests a domain-specific permission, and shows a visible
`MLLminal active` indicator.

The extension does not read cookies, tokens, passwords, or page secrets. It
rejects authentication, payment, and account-security paths. It prepares drafts
and form state only; it never sends email or submits payment.

The native bridge is intentionally a separate local component. Installation
must be explicit and can be skipped; the desktop runtime falls back to local
providers or manual handoff when the extension is not connected.
