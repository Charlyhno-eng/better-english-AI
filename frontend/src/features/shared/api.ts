/** Shared JSON transport: no provider-specific data or automatic retries. */
export async function postJson(path: string, payload: unknown, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, signal,
    body: JSON.stringify(payload),
  });
  let data: unknown;
  try { data = await response.json(); } catch { /* Proxy errors may not be JSON. */ }
  if (!response.ok) {
    const message = isObject(data) && isObject(data.error) && typeof data.error.message === 'string'
      ? data.error.message : `The request failed (HTTP ${response.status}). Please try again.`;
    throw new Error(message);
  }
  return data;
}

export function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

export async function audioBase64(recording: Blob): Promise<string> {
  const bytes = new Uint8Array(await recording.arrayBuffer());
  let binary = '';
  for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
  return btoa(binary);
}
