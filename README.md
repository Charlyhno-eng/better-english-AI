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

Open the **Local** URL printed by the frontend (normally <http://127.0.0.1:5173>; an available port is selected automatically if 5173 is occupied) and select **Setup** to save your GLM API key and install Parakeet, Pocket TTS and OpenPronounce resources. Downloads need internet access and several GB of free disk space; progress and retries are available on that page. No model commands or environment-file editing are needed. The key stays in a private, Git-ignored backend file and takes effect immediately.

Return to the home page for conversation, or choose **Pronunciation practice** or **Writing practice**. Allow microphone access for voice exercises. Learner recordings and conversation history stay in memory; tutoring text is sent to GLM.
