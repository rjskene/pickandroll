import type { ReactElement } from "react";
import type { ViewDef } from "../keys";
import { Chevron } from "./icons";

/** A screen's views (the league page's since #116, the Progress screen's since #129): a narrow
 * drawer at the pane's left edge with a tab per view (its icon, name and key) and a chevron that
 * takes it down to a handle, whose dots mark the view on show. The view keys work either way; `[`
 * shows or hides it. */
export default function ViewDrawer<Id extends string>({
  views,
  icons,
  view,
  shown,
  onView,
  onToggle,
}: {
  views: ViewDef<Id>[];
  icons: Record<Id, ReactElement>;
  view: Id;
  shown: boolean;
  onView: (view: Id) => void;
  onToggle: () => void;
}) {
  if (!shown) {
    return (
      <nav className="views handle" aria-label="Views (drawer hidden)">
        <button className="show" onClick={onToggle} title="Show the view drawer ([)" aria-label="Show the view drawer">
          <Chevron dir="right" />
        </button>
        {views.map((v) => (
          <button key={v.id} className={v.id === view ? "dot on" : "dot"} aria-pressed={v.id === view} aria-label={`${v.title} view`} title={`${v.title} (${v.key})`} onClick={() => onView(v.id)} />
        ))}
      </nav>
    );
  }
  return (
    <nav className="views" aria-label="Views">
      {views.map((v) => (
        <button key={v.id} className={v.id === view ? "tab on" : "tab"} aria-pressed={v.id === view} title={`${v.title}: ${v.blurb} (${v.key})`} onClick={() => onView(v.id)}>
          {icons[v.id]}
          {v.title}
          <kbd>{v.key}</kbd>
        </button>
      ))}
      <span className="grow" />
      <button className="hide" onClick={onToggle} title={`Hide the view drawer: ${views.map((v) => v.key).join(" ")} still switch views, [ shows it`} aria-label="Hide the view drawer">
        <Chevron dir="left" />
      </button>
    </nav>
  );
}
