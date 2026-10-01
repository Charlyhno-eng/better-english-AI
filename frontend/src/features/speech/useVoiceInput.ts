import { useEffect, useRef, useState } from 'react';
import { MAX_RECORDING_SECONDS, microphoneError, VoiceRecorder } from './audio';

type Phase = 'idle' | 'requesting' | 'recording' | 'sending';

/** Own microphone, cancellation and retry in both voice modes. */
export function useVoiceInput<Result>(
  send: (blob: Blob, signal: AbortSignal) => Promise<Result>,
  onResult: (result: Result) => void,
  onStart?: () => void,
) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState('');
  const [elapsed, setElapsed] = useState(0);
  const [pendingRecording, setPendingRecording] = useState<Blob | null>(null);
  const recorder = useRef<VoiceRecorder | null>(null);
  const request = useRef<AbortController | null>(null);
  const operation = useRef(0);
  const phaseRef = useRef<Phase>('idle');
  const finishRef = useRef<() => void>(() => {});

  useEffect(() => () => {
    operation.current++;
    recorder.current?.cancel();
    request.current?.abort();
  }, []);

  useEffect(() => {
    if (phase !== 'recording') return;
    const started = performance.now();
    setElapsed(0);
    const timer = window.setInterval(() => setElapsed(Math.min(MAX_RECORDING_SECONDS,
      Math.floor((performance.now() - started) / 1000))), 250);
    return () => window.clearInterval(timer);
  }, [phase]);

  function changePhase(next: Phase) {
    phaseRef.current = next;
    setPhase(next);
  }

  function cancel() {
    operation.current++;
    recorder.current?.cancel();
    recorder.current = null;
    request.current?.abort();
    request.current = null;
    changePhase('idle');
    setError('');
  }

  async function start() {
    if (phaseRef.current !== 'idle') return;
    const id = ++operation.current;
    setError('');
    setPendingRecording(null);
    onStart?.();
    changePhase('requesting');
    const controller = new AbortController();
    request.current = controller;
    try {
      const capture = await VoiceRecorder.start(
        () => finishRef.current(),
        () => {
          if (id !== operation.current) return;
          cancel();
          setError('Recording was interrupted. Check your microphone and try again.');
        },
        controller.signal,
      );
      if (id !== operation.current) { capture.cancel(); return; }
      request.current = null;
      recorder.current = capture;
      changePhase('recording');
    } catch (failure) {
      if (id !== operation.current) return;
      request.current = null;
      setError(microphoneError(failure));
      changePhase('idle');
    }
  }

  async function submit(blob: Blob, id: number) {
    if (id !== operation.current) return;
    setPendingRecording(blob);
    const controller = new AbortController();
    request.current = controller;
    try {
      const result = await send(blob, controller.signal);
      if (id !== operation.current) return;
      onResult(result);
      setPendingRecording(null);
    } catch (failure) {
      if (id !== operation.current) return;
      setError(failure instanceof TypeError
        ? 'Could not reach the backend. Check your connection and try sending again.'
        : failure instanceof Error ? failure.message : 'The message could not be sent. Please try again.');
    } finally {
      if (id === operation.current) {
        request.current = null;
        changePhase('idle');
      }
    }
  }

  async function finish() {
    const capture = recorder.current;
    if (!capture || phaseRef.current !== 'recording') return;
    const id = operation.current;
    changePhase('sending');
    try {
      const blob = await capture.stop();
      if (id !== operation.current) return;
      recorder.current = null;
      await submit(blob, id);
    } catch (failure) {
      if (id !== operation.current) return;
      capture.cancel();
      recorder.current = null;
      setError(microphoneError(failure));
      changePhase('idle');
    }
  }
  finishRef.current = () => { void finish(); };

  function retry() {
    if (!pendingRecording || phaseRef.current !== 'idle') return;
    setError('');
    changePhase('sending');
    void submit(pendingRecording, ++operation.current);
  }

  function resetInput() { cancel(); setPendingRecording(null); }
  return { phase, error, elapsed, pendingRecording, start, finish, retry, cancel, resetInput };
}
