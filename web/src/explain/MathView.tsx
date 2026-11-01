// Display math (#282) from the formulas' trees, drawn with HTML and CSS: fractions stack, roots
// and parentheses stretch, sums carry their index beneath. No dependency.
import type { ReactNode } from "react";
import type { MathNode } from "./types";

const OPS = new Set(["=", "+", "−", "·", "≤", "≥", "∈", "|", " | "]);

function isObj(n: MathNode): n is Exclude<MathNode, string | MathNode[]> {
  return typeof n === "object" && !Array.isArray(n);
}

function both(base: MathNode, lower: MathNode, upper: MathNode, key?: number): ReactNode {
  return (
    <span key={key} className="m-script">
      {draw(base)}
      <span className="m-stack">
        <sup>{draw(upper)}</sup>
        <sub>{draw(lower)}</sub>
      </span>
    </span>
  );
}

function draw(node: MathNode, key?: number): ReactNode {
  if (typeof node === "string") {
    if (node === ",") return <span key={key} className="m-comma">,</span>;
    if (OPS.has(node)) return <span key={key} className="m-op">{node.trim()}</span>;
    return <span key={key} className="m-t">{node}</span>;
  }
  if (Array.isArray(node)) return <span key={key} className="m-row">{node.map((n, i) => draw(n, i))}</span>;
  if ("v" in node) return <i key={key} className="m-v">{node.v}</i>;
  if ("frac" in node)
    return (
      <span key={key} className="m-frac">
        <span className="m-num">{draw(node.frac[0])}</span>
        <span className="m-den">{draw(node.frac[1])}</span>
      </span>
    );
  // A base with both scripts stacks them, the superscript over the subscript, as type does.
  if ("sub" in node && isObj(node.sub[0]) && "sup" in node.sub[0]) return both(node.sub[0].sup[0], node.sub[1], node.sub[0].sup[1], key);
  if ("sup" in node && isObj(node.sup[0]) && "sub" in node.sup[0]) return both(node.sup[0].sub[0], node.sup[0].sub[1], node.sup[1], key);
  if ("sub" in node)
    return (
      <span key={key} className="m-script">
        {draw(node.sub[0])}
        <sub>{draw(node.sub[1])}</sub>
      </span>
    );
  if ("sup" in node)
    return (
      <span key={key} className="m-script">
        {draw(node.sup[0])}
        <sup>{draw(node.sup[1])}</sup>
      </span>
    );
  if ("sqrt" in node)
    return (
      <span key={key} className="m-sqrt">
        <span className="m-rad">√</span>
        <span className="m-under">{draw(node.sqrt)}</span>
      </span>
    );
  if ("paren" in node)
    return (
      <span key={key} className="m-paren">
        {draw(node.paren)}
      </span>
    );
  if ("big" in node)
    return (
      <span key={key} className="m-big">
        <span className="m-bop">{node.big}</span>
        {node.under !== undefined && <span className="m-lim">{draw(node.under)}</span>}
      </span>
    );
  return (
    <span key={key} className="m-cases">
      <span className="m-brace">{"{"}</span>
      <span className="m-rows">
        {node.cases.map(([e, c], i) => (
          <span key={i} className="m-case">
            <span>{draw(e)}</span>
            <span className="m-cond">{draw(c)}</span>
          </span>
        ))}
      </span>
    </span>
  );
}

/** One expression, inline; `block` sets it as a display line. */
export default function MathView({ node, block }: { node: MathNode; block?: boolean }) {
  return <span className={`ex-math${block ? " block" : ""}`}>{draw(node)}</span>;
}
