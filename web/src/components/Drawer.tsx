import type { ReactElement } from "react";
import { CARDS, useDraft, type CardId } from "../draft";
import Halves from "./Halves";
import AltsCard from "./cards/AltsCard";
import CategoriesCard from "./cards/CategoriesCard";
import LogCard from "./cards/LogCard";
import PickCard from "./cards/PickCard";
import PlanCard from "./cards/PlanCard";
import SolverCard from "./cards/SolverCard";
import TeamCard from "./cards/TeamCard";
import SyncCard from "./cards/SyncCard";

const BODIES: Record<CardId, () => ReactElement> = {
  pick: PickCard,
  cats: CategoriesCard,
  alts: AltsCard,
  plan: PlanCard,
  team: TeamCard,
  log: LogCard,
  solver: SolverCard,
  sync: SyncCard,
};

/** The draft screen's drawer: its eight cards in two halves. */
export default function Drawer() {
  const d = useDraft();
  return (
    <Halves
      d={d}
      cards={CARDS}
      face={(id) => {
        const Body = BODIES[id];
        return { body: <Body /> };
      }}
    />
  );
}
