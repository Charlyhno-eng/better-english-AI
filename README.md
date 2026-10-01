# Better English AI

Practice spoken English, pronunciation and writing with an AI tutor. Local speech models run on CPU; GLM is the only paid API.

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and Node.js 22.12+ with npm. On Debian/Ubuntu, installation also installs missing ffmpeg and eSpeak NG tools (administrator access may be requested). On other systems, these tools must already be available.

From the project root, install once:

```sh
./scripts/install.sh
```

Then start the backend and frontend in separate terminals:

```sh
./scripts/dev-backend.sh
```

```sh
./scripts/dev-frontend.sh
```

Open the **Local** URL printed by the frontend (normally <http://127.0.0.1:5173>; an available port is selected automatically if 5173 is occupied) and select **Setup** to save your GLM API key and install Parakeet, Pocket TTS and OpenPronounce resources. Downloads need internet access and several GB of free disk space; progress and retries are available on that page. No model commands or environment-file editing are needed. The key stays in a private, Git-ignored backend file, takes effect immediately, and can be revealed from Setup when needed.

The frontend development proxy preserves the browser's host so Setup requests pass the backend's same-origin check, including when Vite selects another port. If an already-running frontend returns `403 Forbidden` when saving a key or installing models, restart `./scripts/dev-frontend.sh` to load the updated proxy configuration, then retry from Setup.

The interface uses a dark navy theme with lavender and mint accents, shared navigation across practice pages, and gently animated background glows. Background animation and interface transitions are disabled when your system prefers reduced motion. The layout adapts to smaller screens.

Return to the home page for conversation, or choose **Pronunciation practice** or **Writing practice**. Allow microphone access for voice exercises. Learner recordings and conversation history stay in memory; tutoring text is sent to GLM.

Writing practice is a text chat: a three-dot indicator appears while your partner replies. Messages with grammar or spelling errors show a red, collapsed correction panel; vocabulary or word-choice corrections use orange. Open the panel to read the corrected version and explanations. Error-free replies stay uncluttered, and optional style-only suggestions are hidden in chat. Each request uses up to 25 previous messages (both learner and partner messages), within the configured input character limit. The conversation stays in browser memory until you leave the page; **New conversation** clears it. Cancelled or failed messages remain in the composer for retry. The frontend uses `POST /api/writing/turn` with text and history; the standalone correction endpoint remains available. Feedback focuses on meaningful grammar, spelling, vocabulary, and word-choice issues; punctuation or spacing details alone are left out of the correction list and are normalized in the corrected version.

Voice replies appear as text first and play progressively as Pocket TTS generates audio, so playback no longer waits for the entire WAV or pronunciation analysis. The recording controls stay pinned to the bottom of the window while you scroll through the conversation. Spoken replies use one or two short sentences; language corrections remain separate in the initial GLM request. Pronunciation analysis follows the audio, and coaching uses a separate best-effort GLM request when analysis succeeds. Both share the conversation pronunciation time budget (five seconds by default). The complete voice reply remains available for replay. Select **Stop voice reply** to stop listening while feedback continues, or cancel the request or start a new recording. If your browser blocks automatic playback, use the replay control when the turn finishes.

Installed Parakeet and Pocket TTS models load in the background when the backend starts (`BETTER_ENGLISH_AUDIO__PRELOAD_MODELS=false` disables this). A first message sent before loading finishes can still take longer; subsequent messages reuse the models. GLM response time and CPU speed still affect latency. The frontend uses `POST /api/conversation/turn/stream`, which sends newline-delimited `reply`, `audio`, `feedback`, and `done` events; `audio` events contain playable base64 PCM16 WAV fragments. Reverse proxies should allow unbuffered responses. The original `POST /api/conversation/turn` endpoint remains available for clients that need a single JSON response.

Development code is split by responsibility. In `backend/app`, `api` handles HTTP requests, `services` coordinates tutoring use cases, `ai` and `audio` contain replaceable providers, and `core` owns configuration and errors. In `frontend/src`, `pages` compose the interface and `features` owns conversation, writing and pronunciation behavior. Shared recording code lives in `features/speech`; transport, feedback parsing and correction display live in `features/shared`.

After installation, run the checks from the project root:

```sh
(cd backend && .venv/bin/python -m pytest -q)
(cd frontend && npm test && npm run build)
```

The tests use fake providers and do not require a GLM key or downloaded models. The frontend build includes strict TypeScript checks for unused locals and parameters.
