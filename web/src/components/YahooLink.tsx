import { yahooLeagueUrl } from "../season";
import { YahooIcon } from "./icons";

/** A league's main page on Yahoo in a new tab (#278): an icon link on the landing table's rows,
 * in their panel and in the league page's bar. Its click is the link's alone: the row under it
 * neither opens nor expands. */
export default function YahooLink({ league, title }: { league: string; title: string }) {
  const label = `${title} on Yahoo`;
  return (
    <a className="icon yahoo-link" href={yahooLeagueUrl(league)} target="_blank" rel="noopener noreferrer" aria-label={label} title={label} onClick={(e) => e.stopPropagation()}>
      <YahooIcon />
    </a>
  );
}
