// pickandroll, page half. Runs in the draft client's own JavaScript world at document_start,
// before Yahoo's client opens its socket, and only watches: it adds a message listener to the
// socket Yahoo opens and hands every text frame, with its arrival time, to the content script.
// It never opens a socket, never sends on Yahoo's, and from the client's hello frame it keeps
// the slot number only.
//
// It also runs the content script's timers on a Web Worker: a hidden tab clamps DOM timers to
// once a minute after five minutes, a worker's timers are not clamped.
(() => {
  "use strict";
  const KEY = "__pickandroll";
  if (window[KEY + "Page"]) return;
  Object.defineProperty(window, KEY + "Page", { value: true });

  const origin = location.origin;
  const post = (msg) => window.postMessage({ [KEY]: "page", ...msg }, origin);
  // Frames seen so far, for a content script that starts listening late.
  const frames = [];

  const NativeWebSocket = window.WebSocket;
  const nativeSend = NativeWebSocket.prototype.send;

  function watch(ws) {
    ws.addEventListener("message", (e) => {
      if (typeof e.data !== "string") return;
      const t = Date.now();
      frames.push([e.data, t]);
      if (frames.length > 5000) frames.shift();
      post({ dir: "in", data: e.data, t });
    });
  }

  const Proxied = new Proxy(NativeWebSocket, {
    construct(target, args, newTarget) {
      const ws = Reflect.construct(target, args, newTarget === Proxied ? target : newTarget);
      try {
        watch(ws);
      } catch (_) {
        // never break Yahoo's socket
      }
      return ws;
    },
  });
  window.WebSocket = Proxied;

  NativeWebSocket.prototype.send = function (data) {
    try {
      if (typeof data === "string" && data.startsWith("8|")) {
        const slot = Number(data.split("|")[2]);
        if (slot >= 1 && slot <= 20) post({ dir: "hello", slot });
      }
    } catch (_) {
      // never break Yahoo's socket
    }
    return nativeSend.call(this, data);
  };

  let worker = null;
  try {
    const src = "onmessage=(e)=>setTimeout(()=>postMessage(e.data.id),e.data.ms)";
    worker = new Worker(URL.createObjectURL(new Blob([src], { type: "text/javascript" })));
    worker.onmessage = (e) => post({ dir: "wake", id: e.data });
  } catch (_) {
    worker = null;
  }

  window.addEventListener("message", (e) => {
    if (e.source !== window || !e.data || e.data[KEY] !== "content") return;
    const m = e.data;
    if (m.dir === "sleep") {
      const ms = Math.max(0, Number(m.ms) || 0);
      if (worker) worker.postMessage({ id: m.id, ms });
      else setTimeout(() => post({ dir: "wake", id: m.id }), ms);
    } else if (m.dir === "replay") {
      for (const [data, t] of frames) post({ dir: "in", data, t, replay: true });
    } else if (m.dir === "ping") {
      post({ dir: "ready", worker: Boolean(worker) }); // a content script that started after us
    }
  });
  post({ dir: "ready", worker: Boolean(worker) });
})();
