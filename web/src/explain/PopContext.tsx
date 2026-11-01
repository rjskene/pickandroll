// Which popout to open (#282): a step's worked example or a formula. A card's Example button
// and a bullet's Formula chip open one through this context; the screen holds which is open.
import { createContext, useContext } from "react";
import type { ReactNode } from "react";
import type { FormulaId, TrackId } from "./types";

export type Pop = { kind: "example"; track: TrackId; step: string } | { kind: "formula"; id: FormulaId };

const OpenPop = createContext<(p: Pop) => void>(() => {});

export function PopProvider({ onOpen, children }: { onOpen: (p: Pop) => void; children: ReactNode }) {
  return <OpenPop.Provider value={onOpen}>{children}</OpenPop.Provider>;
}

export const useOpenPop = () => useContext(OpenPop);
