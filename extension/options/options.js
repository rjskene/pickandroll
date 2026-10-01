// pickandroll settings, kept in chrome.storage.local. Only localhost addresses are allowed:
// the extension's host permissions cover localhost and 127.0.0.1 and nothing else.
"use strict";
const FIELDS = ["api", "web", "players_file"];
const LOCAL = /^http:\/\/(localhost|127\.0\.0\.1)(:\d{1,5})?\/?$/;
const $ = (id) => document.getElementById(id);

chrome.storage.local.get(FIELDS).then((s) => {
  for (const k of FIELDS) $(k).value = s[k] || "";
});

$("save").addEventListener("click", async () => {
  const v = Object.fromEntries(FIELDS.map((k) => [k, $(k).value.trim()]));
  for (const k of ["api", "web"]) {
    if (v[k] && !LOCAL.test(v[k])) {
      $("saved").textContent = `${k}: use http://localhost:<port> or http://127.0.0.1:<port>`;
      return;
    }
  }
  if (v.players_file && !/^[A-Za-z0-9_.-]+\.json$/.test(v.players_file)) {
    $("saved").textContent = "players file: a .json file name in data/, no folders";
    return;
  }
  await chrome.storage.local.set(v);
  $("saved").textContent = "Saved.";
});
