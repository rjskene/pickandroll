// The floor's SVG (#461): draws a scene (floor/scene.ts) and nothing else. Every clickable part
// opens a screen the app already has; the handlers come from the face.
import type { KeyboardEvent, ReactNode } from "react";
import { AGENTS, BELT, SIGNS } from "./model";
import type { Agent } from "./model";
import { BELT_Y, DOCK_X, FLOW, GATE, H, HUB, RACK, RACK_X, RAIL_Y, ROOM, SITES, W, lanePath, rackY } from "./scene";
import type { Scene, SiteKey } from "./scene";

export interface StageHandlers {
  onDay: (date: string) => void;
  onDock: (league: string) => void;
  onLamp: (league: string) => void;
  onHub: () => void;
  onGateClock: () => void;
  onLedger: () => void;
  onStation: () => void;
  onStage: (index: number) => void;
  /** One league's floor: back to all the leagues. */
  onAll: () => void;
}

/** A clickable group: a button to the keyboard and the screen reader. */
function Act({ onAct, label, className, transform, children }: { onAct: () => void; label: string; className?: string; transform?: string; children: ReactNode }) {
  const key = (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onAct();
    }
  };
  return (
    <g role="button" tabIndex={0} aria-label={label} className={`fl-act${className ? ` ${className}` : ""}`} transform={transform} onClick={onAct} onKeyDown={key}>
      <title>{label}</title>
      {children}
    </g>
  );
}

const hexPath = (r: number) => {
  let d = "";
  for (let i = 0; i < 6; i++) {
    const a = (Math.PI / 3) * i + Math.PI / 6;
    d += `${i ? "L" : "M"}${(r * Math.cos(a)).toFixed(2)},${(r * Math.sin(a)).toFixed(2)}`;
  }
  return `${d}Z`;
};
const HEX = hexPath(31);

/** The signs' glyphs: a lock (keep rule) and a shield (season guard). */
const SIGN_PATHS = [
  "M-3.4,-0.6 H3.4 a1,1 0 0 1 1,1 V4 a1,1 0 0 1 -1,1 H-3.4 a1,1 0 0 1 -1,-1 V0.4 a1,1 0 0 1 1,-1 Z M-2.4,-0.6 V-2.4 a2.4,2.4 0 0 1 4.8,0 V-0.6",
  "M0,-5 L4.3,-3.4 V0.3 C4.3,2.9 2.3,4.5 0,5.4 C-2.3,4.5 -4.3,2.9 -4.3,0.3 V-3.4 Z",
];
/** The stations' glyphs (no site marks): a sheet, a calendar, a list. */
const GLYPH: Record<SiteKey, string> = {
  bbm: "M6,9H22M6,14H22M6,19H22M11,6V22",
  espn: "M5,10H23M9,15h2M13,15h2M17,15h2M9,19.5h2M13,19.5h2",
  yahoo: "M7,9h1M11,9H22M7,14h1M11,14H22M7,19h1M11,19H22",
};
const MARKS: Record<string, string> = {
  claimed: "M-2.6,0.2 L-0.8,2 L2.8,-2",
  added: "M-2.6,0.2 L-0.8,2 L2.8,-2",
  failed: "M-2.2,-2.2 L2.2,2.2 M2.2,-2.2 L-2.2,2.2",
  gone: "M-2.2,-2.2 L2.2,2.2 M2.2,-2.2 L-2.2,2.2",
  skipped: "M-2.6,-2 L-0.6,0 L-2.6,2 M0.4,-2 L2.4,0 L0.4,2",
};

/** An agent: a clam-shell cart on two wheels (own art). */
function Cart({ x, y, role, open, alpha, flip = false, spin = 0 }: { x: number; y: number; role: Agent; open: number; alpha: number; flip?: boolean; spin?: number }) {
  return (
    <g className={`fl-agent ag-${role}`} transform={`translate(${x.toFixed(1)},${y.toFixed(1)})${flip ? " scale(-1,1)" : ""}`} opacity={alpha}>
      <ellipse cx={0} cy={11.6} rx={11} ry={1.5} className="ag-shadow" />
      {[-6.5, 6.5].map((wx) => (
        <g key={wx} transform={`translate(${wx},8) rotate(${spin.toFixed(0)})`}>
          <circle r={3.2} className="ag-wheel" />
          <path d="M-3.2,0H3.2M0,-3.2V3.2" className="ag-spoke" />
        </g>
      ))}
      <path d="M-12,0.6 H11 a1.5,1.5 0 0 1 1.5,1.5 V3 a4,4 0 0 1 -4,4 H-8 a4,4 0 0 1 -4,-4 Z" className="ag-body" />
      <path d="M-1,0.6 H12.2 V2.4 H-1 Z" className="ag-mouth" />
      <g transform={`rotate(${(-26 * open).toFixed(1)},-12,0)`}>
        <path d="M-12,0 V-4 a6,6 0 0 1 6,-6 H5 a7.5,7.5 0 0 1 7.5,7.5 V0 Z" className="ag-body" />
        <path d="M-9.5,-3.4 H-4.5" className="ag-stripe" />
        <circle cx={6} cy={-4.6} r={2.4} className="ag-eye" />
        <circle cx={6.9} cy={-5} r={0.95} className="ag-pupil" />
        <path d="M-5,-10 V-13.4" className="ag-ant" />
        <circle cx={-5} cy={-14.4} r={1.3} className="ag-tip" />
      </g>
    </g>
  );
}

/** A rule's boom gate, its arm lifted by ``open`` (0 to 1). */
function Boom({ x, y, h, open }: { x: number; y: number; h: number; open: number }) {
  return (
    <g className="fl-gate" transform={`translate(${x.toFixed(1)},${y.toFixed(1)})`}>
      <rect x={-1.2} y={-h} width={2.4} height={h} className="gt-post" />
      <g transform={`rotate(${(-74 * open).toFixed(0)},0,${-h})`}>
        <rect x={-1} y={-h - 1.7} width={15} height={3.4} rx={1} className="gt-arm" fill="url(#fl-hz)" />
      </g>
    </g>
  );
}

export default function FloorStage({ s, one, h }: { s: Scene; one: string | null; h: StageHandlers }) {
  return (
    <svg className="fl-svg" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMinYMin meet" role="img" aria-label="The floor: the agents at work, from the reads to the execute time and out">
      <defs>
        <pattern id="fl-hz" width={5} height={5} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width={5} height={5} className="fl-hz-a" />
          <rect width={2.5} height={5} className="fl-hz-b" />
        </pattern>
      </defs>
      {/* the week strip */}
      {s.days.map((d, k) => (
        <Act key={d.date} onAct={() => h.onDay(d.date)} label={`${d.label}: the day`} className={`fl-day${d.on ? " on" : ""}`} transform={`translate(${14 + k * 179.3},4)`}>
          <rect width={172} height={50} rx={8} />
          <text x={10} y={19} className="d fl-daytitle">
            {d.label}
          </text>
          <text x={163} y={19} textAnchor="end" className="fl-tally">
            {d.tally.claimed + d.tally.held + d.tally.failed + d.tally.skipped > 0 && (
              <>
                <tspan className="g">✓ {d.tally.claimed}</tspan>
                {d.tally.held > 0 && <tspan className="h">{`  ${d.tally.held} held`}</tspan>}
                {d.tally.failed > 0 && <tspan className="b">{`  ✕ ${d.tally.failed}`}</tspan>}
              </>
            )}
          </text>
          {d.pips.slice(0, 13).map((p, i) => (
            <circle key={i} cx={14 + i * 12} cy={36} r={3.6} className={`fl-pip ${p.state}`}>
              <title>{p.title}</title>
            </circle>
          ))}
        </Act>
      ))}
      {/* the flow: a caption a stage, its number on the floor */}
      {FLOW.map((f, i) => {
        const on = s.stage === i + 1;
        const x = 20 + i * 141;
        return (
          <g key={f.title} className={`fl-flow${on ? " on" : ""}`}>
            <Act onAct={() => h.onStage(i)} label={`${i + 1} · ${f.title}: open its step in Explain`}>
              <circle cx={x + 9} cy={78} r={9} />
              <text x={x + 9} y={82} textAnchor="middle" className="n">
                {i + 1}
              </text>
              <text x={x + 24} y={83} className="d t">
                {f.title}
              </text>
            </Act>
            {f.lines.map((l, j) => (
              <text key={j} x={x} y={99 + j * 12} className="p">
                {l}
              </text>
            ))}
          </g>
        );
      })}
      {/* the moves engine */}
      <rect x={20} y={146} width={170} height={192} rx={10} className="fl-box" />
      <text x={32} y={167} className="d fl-h">
        Moves engine
      </text>
      <text x={32} y={180} className="fl-sub">
        reads in, recommended sets out
      </text>
      {s.lamps.map((l) => (
        <Act key={l.league} onAct={() => h.onLamp(l.league)} label={`${l.league}: its Moves view`} className={`fl-lampg${l.off ? " off" : ""}`}>
          <rect x={l.x} y={l.y} width={72} height={21} rx={5} className={`fl-lamp ${l.state}`} />
          <text x={l.x + 36} y={l.y + 14.5} textAnchor="middle" className={`fl-lamptxt ${l.state}`}>
            {l.league}
          </text>
        </Act>
      ))}
      {(["read", "solving", "solved"] as const).map((c, k) => (
        <g key={c}>
          <rect x={[30, 70, 126][k]} y={322} width={11} height={9} rx={2.5} className={`fl-lamp ${c}`} />
          <text x={[30, 70, 126][k] + 15} y={330} className="fl-key">
            {c}
          </text>
        </g>
      ))}
      {/* the Solver's rail and the key of its two signs */}
      <line x1={26} x2={186} y1={RAIL_Y + 10} y2={RAIL_Y + 10} className="fl-lead" />
      {s.rail.map((p, k) => (
        <circle key={k} cx={44 + k * 15} cy={RAIL_Y} r={2.5} className={`fl-pl solver ${p}`} />
      ))}
      {SIGNS.map((r, k) => (
        <g key={r.key}>
          <path d={SIGN_PATHS[k]} transform={`translate(${26 + k * 62 + 5},${RAIL_Y + 22.5})`} className={`fl-sign ${s.solver.key[k] ? "hot" : "on"}`} />
          <text x={26 + k * 62 + 14} y={RAIL_Y + 26} className={`fl-key${s.solver.key[k] ? " hot" : ""}`}>
            {r.tag}
            <title>{k ? "part of the solve: every search holds the set's rest of the season at zero or more; the queue checks each move again" : "part of the solve: no search drops a protected player; the queue reads the list again"}</title>
          </text>
        </g>
      ))}
      <text x={168} y={RAIL_Y + 26} className="fl-knob">
        {s.solver.text}
      </text>
      {/* the belt, the hub, the rules */}
      <line x1={196} x2={GATE.x - 6} y1={BELT_Y} y2={BELT_Y} className="fl-belt" />
      <line x1={196} x2={GATE.x - 6} y1={BELT_Y} y2={BELT_Y} className="fl-beltdash" />
      <Act onAct={h.onHub} label="The orchestrator: open the Queue" transform={`translate(${HUB.x},${HUB.y})`} className="fl-hubg">
        <path d={HEX} className="fl-hub" />
        <circle r={23} className="fl-ring" transform={`rotate(${s.hub.spin.toFixed(0)})`} opacity={s.hub.building ? 1 : 0.25} />
        <text y={8} textAnchor="middle" className="d fl-hubn">
          {s.hub.n}
        </text>
      </Act>
      <text x={HUB.x} y={HUB.y - 42} textAnchor="middle" className="d fl-h">
        Orchestrator
      </text>
      <text x={HUB.x} y={HUB.y + 52} textAnchor="middle" className="fl-sub">
        {s.hub.text}
      </text>
      {s.gates.map((g) => (
        <g key={g.key}>
          <line x1={g.x} x2={g.x} y1={BELT_Y - 12} y2={BELT_Y - g.up + 14} className="fl-lead" />
          <Boom x={g.x} y={BELT_Y + 9} h={19} open={g.open} />
          <text x={g.x} y={BELT_Y - g.up} textAnchor="middle" className={`fl-rule${g.hot ? " hot" : ""}`}>
            {g.tag}
            <title>{g.title}</title>
          </text>
          <text x={g.x} y={BELT_Y - g.up + 11} textAnchor="middle" className="fl-knob">
            {g.knob}
          </text>
        </g>
      ))}
      {/* the execute-time gate */}
      <Boom x={GATE.x - 5} y={BELT_Y + 9} h={30} open={s.gate.open} />
      <Act onAct={h.onGateClock} label={`The execute time, ${s.gate.face} CT: set it`}>
        <circle cx={GATE.x - 5} cy={BELT_Y - 50} r={17} className="fl-face" />
        <text x={GATE.x - 5} y={BELT_Y - 46.5} textAnchor="middle" className="fl-facetxt">
          {s.gate.face}
        </text>
      </Act>
      <text x={GATE.x - 5} y={BELT_Y - 73} textAnchor="middle" className="fl-knob">
        execute time
      </text>
      <text x={GATE.x - 14} y={BELT_Y + 24} textAnchor="end" className="fl-veto">
        {s.gate.veto}
      </text>
      {/* the lanes out to the leagues */}
      {s.lanes.map((l) => (
        <g key={l.key}>
          <path d={lanePath(l.y, l.x1)} className="fl-lane" />
          <path d={lanePath(l.y, l.x1)} className={`fl-lanehot${l.color ? ` c-${l.color}` : ""}`} opacity={l.hot} />
        </g>
      ))}
      {s.docks.map((d) => (
        <Act key={d.league} onAct={() => h.onDock(d.league)} label={`${d.league}: open its page`} className={`fl-dock${d.mine ? " mine" : ""}`} transform={`translate(${DOCK_X},${d.y - 22})`}>
          <rect className="card" width={220} height={44} rx={8} />
          <text x={12} y={19} className="d fl-dockid">
            {d.league}
          </text>
          {d.pips.map((on, j) => (
            <rect key={j} x={72 + j * 9} y={9} width={6} height={6} rx={1.5} className={`fl-pipq${on ? " on" : ""}`} />
          ))}
          <text x={208} y={18} textAnchor="end" className={`fl-bud${d.mine ? " mine" : ""}`}>
            {d.budget}
          </text>
          <text x={12} y={35} className={`fl-dockres fl-res ${d.cls}`}>
            {d.res}
          </text>
        </Act>
      ))}
      {s.court && (
        <>
          <Act onAct={() => h.onDock(s.court!.league)} label={`${s.court.league}: open its page`} className={`fl-court${s.court.mine ? " mine" : ""}`}>
            <rect x={1000} y={78} width={266} height={440} rx={10} className="fl-box" />
            <text x={1012} y={106} className="d fl-courtid">
              {s.court.league}
            </text>
            <text x={1012} y={122} className="fl-sub">
              {s.court.sub}
            </text>
            <text x={1012} y={140} className={`fl-dockres fl-res ${s.court.cls}`}>
              {s.court.res}
            </text>
            {s.court.tiles.length === 0 && (
              <text x={1012} y={170} className="fl-knob">
                reading the roster…
              </text>
            )}
          </Act>
          {s.court.tiles.slice(0, 16).map((tile, k) => (
            <g key={k} className={`fl-tile${tile.name ? "" : " open"}${tile.state ? ` ${tile.state}` : ""}`} transform={`translate(${1010 + (k < 8 ? 0 : 126)},${152 + (k % 8) * 45})`}>
              <rect width={120} height={38} rx={6} />
              <text x={8} y={14} className="fl-slot">
                {tile.slot}
              </text>
              <text x={8} y={29} className="fl-nm">
                {tile.name ?? "open spot"}
              </text>
            </g>
          ))}
          <Act onAct={h.onAll} label="The other leagues: back to all" className="fl-dock" transform="translate(1000,556)">
            <rect className="card" width={266} height={44} rx={8} />
            <text x={12} y={19} className="d fl-dockid muted">
              The other leagues
            </text>
            <text x={12} y={35} className={`fl-dockres fl-res ${s.court.other.cls}`}>
              {s.court.other.res}
            </text>
          </Act>
        </>
      )}
      {/* the rack */}
      {RACK.map((r, k) => (
        <text key={r} x={RACK_X - 30} y={rackY(k) + 3} textAnchor="end" className={`fl-rack c-${r}`}>
          {AGENTS[r].label}
        </text>
      ))}
      {/* the Sources room */}
      <text x={20} y={450} className="d fl-h">
        Sources
      </text>
      <text x={112} y={449} className="fl-sub">
        the sites the Scout reads. It only reads: nothing here clicks.
      </text>
      <path d={`M24,${ROOM.y + 12} H526`} className="fl-lead" />
      <path d={`M526,${ROOM.line} H10 V250 H20`} className="fl-road" />
      <path d={`M526,${ROOM.line} H${ROOM.up} V${ROOM.over} H${ROOM.gx} V296 H${GATE.x - 5} V${BELT_Y + 12}`} className="fl-road" />
      <text x={ROOM.up + 16} y={ROOM.over - 7} className="fl-knob">
        reads made at a pass go to the execute-time check, not the engine
      </text>
      <text x={24} y={596} className="fl-knob">
        reads for the solve ride into the engine
      </text>
      {SITES.map((st) => (
        <g key={st.key}>
          <Act onAct={h.onStation} label={`${st.name}: the updates sheet`} className={`fl-site${s.scout.on === st.key ? " on" : ""}`} transform={`translate(${st.x0},462)`}>
            <rect width={28} height={28} rx={6} />
            <path d={GLYPH[st.key]} />
            <text x={36} y={19} className="d nm">
              {st.name}
            </text>
            <text x={0} y={40} className="sub">
              {st.sub}
            </text>
          </Act>
          {s.scout.pellets[st.key].map((p, k) => (
            <rect key={k} x={st.px(k) - 4} y={ROOM.y - 5} width={8} height={10} rx={1.8} className={`fl-pl scout ${p}`} />
          ))}
        </g>
      ))}
      <text x={ROOM.rest} y={ROOM.y + 23} textAnchor="middle" className="fl-rack c-scout">
        Scout
      </text>
      {/* the ledger */}
      <Act onAct={h.onLedger} label="The ledger: open History" className="fl-ledgerg">
        <rect x={ROOM.ledger - 6} y={430} width={300} height={176} fill="transparent" />
        <text x={ROOM.ledger} y={446} className="d fl-h">
          {one ? `Ledger · ${one}` : "Ledger"}
        </text>
        {s.ledger.map((l, k) => (
          <text key={k} x={ROOM.ledger} y={466 + k * 19} className="fl-ledger" opacity={1 - k * 0.12}>
            <tspan className="t">{`${l.at}  `}</tspan>
            <tspan className={`fl-res ${l.cls}`}>{l.text}</tspan>
          </text>
        ))}
      </Act>
      {/* the entries */}
      {s.tokens.map((tk) => (
        <g key={tk.id}>
          <g className={`fl-tok ${tk.state}`} transform={`translate(${tk.x.toFixed(1)},${tk.y.toFixed(1)}) scale(${tk.k.toFixed(2)})`}>
            <title>{tk.title}</title>
            <circle r={5.2} className="tk-ring" />
            <circle r={2.1} className="tk-core" />
            <circle r={7.8} className="tk-arc" pathLength={100} transform="rotate(-90)" strokeDasharray={tk.state === "doing" ? `${(tk.p * 100).toFixed(0)} 100` : "0 100"} />
            <path d={MARKS[tk.state] ?? ""} className="tk-mark" />
          </g>
          {tk.label && (
            <>
              <text x={tk.label.x} y={tk.label.y} textAnchor={tk.label.anchor} className={`fl-rule${tk.label.hot ? " hot" : ""}`}>
                {tk.label.text}
              </text>
              <text x={tk.label.x} y={tk.label.y + 11} textAnchor={tk.label.anchor} className="fl-knob">
                {tk.label.sub}
              </text>
            </>
          )}
        </g>
      ))}
      {s.steps3.map((c, k) => (
        <circle key={k} cx={c.x} cy={c.y} r={3} className={`fl-step${c.done ? " done" : ""}`} />
      ))}
      {/* the agents */}
      <Cart x={s.solver.x} y={RAIL_Y - 1} role="solver" open={s.solver.open} alpha={s.solver.alpha} spin={s.solver.x * 14} />
      <g transform={`translate(${s.solver.x.toFixed(1)},${RAIL_Y - 1})`} opacity={s.solver.alpha}>
        {[-9, 6].map((dx, k) => (
          <g key={dx}>
            <line x1={dx} x2={dx} y1={-11} y2={-17.5} className="fl-pole" />
            <path d={SIGN_PATHS[k]} transform={`translate(${dx},-23)`} className={`fl-sign ${s.solver.signs[k]}`} />
          </g>
        ))}
      </g>
      {s.agents.map((a) => (
        <Cart key={a.role} x={a.x} y={a.y} role={a.role} open={a.open} alpha={a.alpha} spin={a.x * 13} />
      ))}
      <Cart x={s.scout.x} y={ROOM.y} role="scout" open={s.scout.open} alpha={s.scout.alpha} flip={s.scout.flip} spin={s.scout.x * 13} />
      {s.scout.label && (
        <text x={Math.max(86, Math.min(440, s.scout.x))} y={ROOM.line + 19} textAnchor="middle" className="fl-subl">
          {`${s.scout.label}…`}
        </text>
      )}
      {s.scout.pulses.map(([x, y], k) => (
        <circle key={k} cx={x} cy={y} r={3} className="fl-pulse" />
      ))}
      {s.chips.map((c, k) => (
        <circle key={k} cx={c.x} cy={c.y} r={3.6} className={`fl-chip ${c.outcome}`} />
      ))}
      {s.sub && (
        <text x={s.sub.x} y={s.sub.y} textAnchor="middle" className="fl-subl">
          {s.sub.text}
        </text>
      )}
      {/* the stage's number pinned on the floor where it happens */}
      {FLOW.map((f, i) => (
        <g key={f.title} className={`fl-flow fl-pin${s.stage === i + 1 ? " on" : ""}`} transform={`translate(${f.at[0]},${f.at[1]})`}>
          <circle r={8} />
          <text y={3.6} textAnchor="middle" className="n">
            {i + 1}
          </text>
        </g>
      ))}
      {/* the belt's rules in the queue's order, named for the screen reader */}
      <desc>{`The queue's rules in order: ${BELT.map((r) => r.tag).join(", ")}.`}</desc>
    </svg>
  );
}
