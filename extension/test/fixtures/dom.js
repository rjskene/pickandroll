// A captured fixture's markup read into the fake DOM the tests use (#239): elements with their tag,
// attributes, children, parent and text, and querySelector(All) for the selectors the content
// scripts ask of a pending box: tag names, `tag[attr*="v"]`, `#id` and comma lists of those. The
// fixtures are well formed; nothing here is a general HTML parser.
"use strict";

const ENTITIES = { amp: "&", quot: '"', lt: "<", gt: ">", "#39": "'" };
const decode = (s) => s.replace(/&(amp|quot|lt|gt|#39);/g, (_, k) => ENTITIES[k]);
const VOID = /^(br|hr|img|input|meta|link)$/i;

function descendants(n) {
  return n.children.flatMap((c) => [c, ...descendants(c)]);
}

function matches(e, sel) {
  return sel.split(",").some((part) => {
    const s = part.trim();
    let m = /^#([\w-]+)$/.exec(s);
    if (m) return e.getAttribute("id") === m[1];
    m = /^([a-z0-9]+)?(?:\[([\w-]+)\*="([^"]*)"\])?$/i.exec(s);
    if (!m || (!m[1] && !m[2])) throw new Error(`the fixture DOM does not read the selector ${s}`);
    return (!m[1] || e.tagName === m[1].toUpperCase()) && (!m[2] || (e.getAttribute(m[2]) || "").includes(m[3]));
  });
}

function element(tag, attrs, parent) {
  const e = {
    tagName: tag.toUpperCase(),
    children: [],
    nodes: [],
    parentElement: parent,
    getAttribute: (a) => (Object.hasOwn(attrs, a) ? attrs[a] : null),
    get className() {
      return attrs.class || "";
    },
    get textContent() {
      return e.nodes.map((n) => (typeof n === "string" ? n : n.textContent)).join("");
    },
    querySelectorAll: (sel) => descendants(e).filter((d) => matches(d, sel)),
    querySelector: (sel) => e.querySelectorAll(sel)[0] || null,
    closest: () => null,
  };
  return e;
}

/** The fixture ``html`` as a root element holding its top-level elements. */
function parse(html) {
  const root = element("#root", {}, null);
  let at = root;
  for (const [, close, tag, rest, text] of html.matchAll(/<(\/?)([a-z0-9]+)([^>]*)>|([^<]+)/gi)) {
    if (text !== undefined) {
      at.nodes.push(decode(text));
    } else if (close) {
      if (at.tagName !== tag.toUpperCase()) throw new Error(`</${tag}> closes <${at.tagName.toLowerCase()}>`);
      at = at.parentElement;
    } else {
      const attrs = Object.fromEntries([...rest.matchAll(/([\w-]+)="([^"]*)"/g)].map(([, k, v]) => [k, decode(v)]));
      const e = element(tag, attrs, at);
      at.children.push(e);
      at.nodes.push(e);
      if (!VOID.test(tag)) at = e;
    }
  }
  if (at !== root) throw new Error(`<${at.tagName.toLowerCase()}> is never closed`);
  return root;
}

/** Every text of ``root``, trimmed, the blank ones left out. */
function texts(root) {
  const out = [];
  const walk = (e) => e.nodes.forEach((n) => (typeof n === "string" ? n.trim() && out.push(n.trim()) : walk(n)));
  walk(root);
  return out;
}

module.exports = { parse, texts };
