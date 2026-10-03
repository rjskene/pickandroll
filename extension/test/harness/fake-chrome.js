// A stand-in for the chrome.* APIs the extension uses, for the harness pages: runtime messaging
// and ports between the page's scripts (sender = tab 1), storage.local / storage.session in
// memory, and the calls the side panel makes. worker.js loaded into the same page answers it.
window.makeFakeChrome = function makeFakeChrome() {
  "use strict";
  const listeners = { message: [], connect: [], changed: [] };
  const store = { local: {}, session: {} };
  const area = (name) => ({
    async get(keys) {
      const all = store[name];
      if (keys == null) return { ...all };
      const list = Array.isArray(keys) ? keys : [keys];
      return Object.fromEntries(list.filter((k) => k in all).map((k) => [k, all[k]]));
    },
    async set(obj) {
      Object.assign(store[name], obj);
      listeners.changed.forEach((fn) => fn(obj, name));
    },
    async remove(key) {
      delete store[name][key];
    },
  });
  const evt = (list) => ({ addListener: (fn) => list.push(fn) });
  const sender = { tab: { id: 1 } };
  const chrome = {
    runtime: {
      lastError: undefined,
      onMessage: evt(listeners.message),
      onConnect: evt(listeners.connect),
      onInstalled: evt([]),
      onStartup: evt([]),
      sendMessage(msg) {
        return new Promise((resolve) => {
          const copy = JSON.parse(JSON.stringify(msg));
          for (const fn of listeners.message) if (fn(copy, sender, resolve) === true) return;
          resolve(undefined);
        });
      },
      connect({ name }) {
        const a = { msg: [], dis: [] };
        const b = { msg: [], dis: [] };
        const side = (mine, theirs) => ({
          name,
          sender,
          postMessage: (m) => theirs.msg.forEach((fn) => fn(m)),
          onMessage: evt(mine.msg),
          onDisconnect: evt(mine.dis),
          disconnect: () => theirs.dis.forEach((fn) => fn()),
        });
        const contentSide = side(a, b);
        listeners.connect.forEach((fn) => fn(side(b, a)));
        return contentSide;
      },
      openOptionsPage() {},
    },
    storage: { local: area("local"), session: area("session"), onChanged: evt(listeners.changed) },
    tabs: {
      async query() {
        return [{ id: 1 }];
      },
      onActivated: evt([]),
    },
    sidePanel: { setPanelBehavior: async () => {} },
  };
  return { chrome, store };
};
