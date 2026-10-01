import assert from 'node:assert/strict';
import { once } from 'node:events';
import { createServer as createHttpServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { createServer } from 'vite';

test('setup proxy preserves Host and Origin on a fallback frontend port', async (t) => {
  const backend = createHttpServer((request, response) => {
    response.setHeader('Content-Type', 'application/json');
    response.end(JSON.stringify({
      host: request.headers.host,
      origin: request.headers.origin ?? null,
      method: request.method,
      path: request.url,
    }));
  });
  t.after(() => new Promise((resolve) => backend.close(resolve)));
  backend.listen(0, '127.0.0.1');
  await once(backend, 'listening');
  const backendPort = backend.address().port;
  const previousTarget = process.env.BACKEND_URL;
  process.env.BACKEND_URL = `http://127.0.0.1:${backendPort}`;
  t.after(() => {
    if (previousTarget === undefined) delete process.env.BACKEND_URL;
    else process.env.BACKEND_URL = previousTarget;
  });

  const frontend = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    configFile: fileURLToPath(new URL('../vite.config.ts', import.meta.url)),
    logLevel: 'silent',
    server: {
      host: '127.0.0.1',
      // Occupy the requested port to exercise Vite's automatic port selection.
      port: backendPort,
      strictPort: false,
      watch: null,
      hmr: false,
    },
  });
  t.after(() => frontend.close());
  await frontend.listen();
  const frontendPort = frontend.httpServer.address().port;
  assert.notEqual(frontendPort, backendPort);
  const origin = `http://127.0.0.1:${frontendPort}`;

  for (const path of ['/api/setup/models/parakeet', '/api/setup/models/openpronounce',
    '/api/setup/models/pocket-tts', '/api/setup/glm']) {
    const response = await fetch(`${origin}${path}`, {
      method: 'POST', headers: { Origin: origin, 'Content-Type': 'application/json' },
      body: '{}',
    });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), {
      host: `127.0.0.1:${frontendPort}`, origin, method: 'POST', path,
    });
  }

  // The proxy must not turn foreign or missing origins into trusted ones.
  for (const suppliedOrigin of ['https://untrusted.example', null]) {
    const response = await fetch(`${origin}/api/setup/models/parakeet`, {
      method: 'POST', headers: suppliedOrigin ? { Origin: suppliedOrigin } : {},
    });
    const forwarded = await response.json();
    assert.equal(forwarded.host, `127.0.0.1:${frontendPort}`);
    assert.equal(forwarded.origin, suppliedOrigin);
  }
});
