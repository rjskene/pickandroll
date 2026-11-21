// The in-season page's two faces (#461): the floor or today's leagues list, under the same bar.
// Plain state, never saved: the page opens on the list in this PR (PR 5 flips the default), and
// coming back from a league page or a screen opens it again on the default face.

export type Face = "floor" | "list";

/** The face the in-season page opens on. */
export const DEFAULT_FACE: Face = "list";

/** The other face. */
export const flipFace = (f: Face): Face => (f === "floor" ? "list" : "floor");

/** The face drawn: the list on a phone and on the draft-season page, which have no flip icon. */
export const faceShown = (f: Face, page: "season" | "draft", phone: boolean): Face => (page === "season" && !phone ? f : "list");

/** Whether the bar carries the flip icon. */
export const hasFlip = (page: "season" | "draft", phone: boolean): boolean => page === "season" && !phone;

/** The flip icon's words: on the floor it offers the list, on the list the floor. */
export const flipLabel = (f: Face): string => (f === "floor" ? "The leagues list (f)" : "The floor: the agents at work (f)");
