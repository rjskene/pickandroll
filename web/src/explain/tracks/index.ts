// Every track the walkthrough shows, in reading order; the screen and the text-rule test both
// read this list, so a track is registered once. The `.ts` extensions let Node run the test
// without a build (tsconfig: allowImportingTsExtensions).
import type { Track } from "../types";
import { daily } from "./daily.ts";
import { draft } from "./draft.ts";
import { moves } from "./moves.ts";

export const TRACKS: Track[] = [draft, moves, daily];

export const trackById = (id: string): Track | undefined => TRACKS.find((t) => t.id === id);
