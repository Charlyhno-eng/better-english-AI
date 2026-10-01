import { useEffect, useRef, useState } from 'react';

export function ReplyAudio({ blob, paused, autoPlay = true, onPlayback }: {
  blob: Blob; paused: boolean; autoPlay?: boolean; onPlayback?: () => void;
}) {
  const player = useRef<HTMLAudioElement>(null);
  const [hint, setHint] = useState('');

  useEffect(() => {
    const audio = player.current!;
    const url = URL.createObjectURL(blob);
    audio.src = url;
    if (autoPlay) void audio.play().catch(() => setHint('Press play to hear the reply.'));
    return () => {
      audio.pause();
      audio.removeAttribute('src');
      audio.load();
      URL.revokeObjectURL(url);
    };
  }, [blob, autoPlay]);

  useEffect(() => {
    if (paused) player.current?.pause();
  }, [paused]);

  return (
    <div className="reply-audio">
      <audio ref={player} controls preload="metadata" aria-label="Play AI voice reply"
        onPlay={() => {
          if (paused) {
            player.current?.pause();
            setHint('Playback is paused while recording or sending a message.');
          } else { onPlayback?.(); setHint(''); }
        }} onError={() => setHint('Audio playback failed. The text reply is still available.')} />
      {hint && <p className="audio-hint">{hint}</p>}
    </div>
  );
}
