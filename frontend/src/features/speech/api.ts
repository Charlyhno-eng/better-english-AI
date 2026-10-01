/** Fetch an AI reply as a WAV blob, ready for URL.createObjectURL and <audio>. */
export async function synthesizeSpeech(text: string, signal?: AbortSignal): Promise<Blob> {
  const response = await fetch('/api/audio/speech', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
    signal,
  });
  if (!response.ok) {
    throw new Error(`Speech synthesis failed (HTTP ${response.status}).`);
  }
  return response.blob();
}
