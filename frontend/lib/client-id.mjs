/**
 * Browser-safe idempotency keys and client-owned identifiers.
 *
 * `crypto.randomUUID()` is only exposed in secure contexts. The platform is
 * deployed behind plain HTTP on some intranet/public-IP entry points, so a
 * missing randomUUID must not crash a page during render or event handling.
 */
export function createClientId(prefix = "", cryptoApi = globalThis.crypto) {
  const randomUUID = cryptoApi?.randomUUID;
  if (typeof randomUUID === "function") {
    return `${prefix}${String(randomUUID.call(cryptoApi)).replaceAll("-", "")}`;
  }

  const getRandomValues = cryptoApi?.getRandomValues;
  if (typeof getRandomValues === "function") {
    const bytes = new Uint8Array(16);
    getRandomValues.call(cryptoApi, bytes);
    return `${prefix}${Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("")}`;
  }

  const random = Math.random().toString(36).slice(2).padEnd(16, "0").slice(0, 16);
  return `${prefix}${Date.now().toString(36)}${random}`;
}
