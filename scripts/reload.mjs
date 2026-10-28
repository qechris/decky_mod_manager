// Ask Decky to reload this plugin's backend through the Steam CEF debugger.
// usage: node scripts/reload.mjs <cef port>
const port = process.argv[2];
const page = (await (await fetch(`http://localhost:${port}/json`)).json()).find((p) => p.title === "SharedJSContext");
const ws = new WebSocket(page.webSocketDebuggerUrl.replace(/localhost:\d+/, `localhost:${port}`));
await new Promise((r) => (ws.onopen = r));
ws.send(JSON.stringify({
  id: 1,
  method: "Runtime.evaluate",
  params: { expression: 'DeckyBackend.call("loader/reload_plugin", "Mod Manager").then(() => "reloaded")', awaitPromise: true, returnByValue: true },
}));
ws.onmessage = (m) => {
  const res = JSON.parse(m.data).result;
  console.log(res.exceptionDetails ? res.exceptionDetails.exception.description : res.result.value);
  ws.close();
};
