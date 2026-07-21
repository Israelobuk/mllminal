# Native browser bridge boundary

The native bridge is a local-only, loopback component that exchanges versioned
semantic operations with the MLLminal extension. It must reject arbitrary
JavaScript, cookies, tokens, passwords, and security/payment URLs. Each domain
requires an explicit capability grant. The bridge returns provider selection,
draft-only state, and verification evidence to the desktop runtime.

The Python seam is implemented in `src/mllminal/apps/browser_bridge.py`; this
directory documents the packaging boundary for a future signed native-messaging
host.
