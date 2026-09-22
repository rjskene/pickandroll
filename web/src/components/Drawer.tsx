import { useRef, type CSSProperties, type ReactElement } from "react";
import { CARDS, cardIndex, useDraft, type CardId, type Half } from "../draft";
import { Chevron, Grip, Swap } from "./icons";
import AltsCard from "./cards/AltsCard";
import LogCard from "./cards/LogCard";
import PickCard from "./cards/PickCard";
import PlanCard from "./cards/PlanCard";
import SolverCard from "./cards/SolverCard";
import TeamCard from "./cards/TeamCard";

const BODIES: Record<CardId, () => ReactElement> = {
  pick: PickCard,
  alts: AltsCard,
  plan: PlanCard,
  team: TeamCard,
  log: LogCard,
  solver: SolverCard,
};

function CardFrame({ id, half, style }: { id: CardId; half: Half; style: CSSProperties }) {
  const d = useDraft();
  const i = cardIndex(id);
  const Body = BODIES[id];
  return (
    <section className="card" style={style} aria-label={CARDS[i].title}>
      <header>
        <h2>{CARDS[i].title.toUpperCase()}</h2>
        <span className="dim">
          {half} · card {i + 1} of {CARDS.length}
        </span>
        <span className="grow" />
        {d.drawer.top && d.drawer.bottom && (
          <button className="icon" aria-label="Swap the top and bottom cards" title="Swap halves (x)" onClick={d.swapHalves}>
            <Swap />
          </button>
        )}
        <button className="icon" aria-label={`Close ${CARDS[i].title}`} title={`Close (${i + 1})`} onClick={() => d.closeCard(id)}>
          <Chevron dir={half === "top" ? "up" : "down"} />
        </button>
      </header>
      <div className="body">
        <Body />
      </div>
    </section>
  );
}

export default function Drawer() {
  const d = useDraft();
  const ref = useRef<HTMLElement | null>(null);
  if (!d.drawerOpen) return null;
  const { top, bottom, split } = d.drawer;

  const startDrag = (e: React.PointerEvent) => {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const move = (ev: PointerEvent) => d.setSplit((ev.clientY - rect.top) / rect.height);
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    e.preventDefault();
  };

  return (
    <aside className="drawer" ref={ref}>
      {top && <CardFrame id={top} half="top" style={{ flex: bottom ? `${split} 1 0%` : "1 1 0%" }} />}
      {top && bottom && (
        <div className="divider" role="separator" aria-orientation="horizontal" title="Drag to resize · x swaps the halves" onPointerDown={startDrag}>
          <Grip />
        </div>
      )}
      {bottom && <CardFrame id={bottom} half="bottom" style={{ flex: top ? `${1 - split} 1 0%` : "1 1 0%" }} />}
    </aside>
  );
}
