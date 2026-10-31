/** The app bar's pick&roll badge (#253): a link to the landing page, the app's own home (it
 * leaves a league, Progress, the Queue or a draft session without a page load). A click with a
 * modifier key is the browser's (a new tab). */
export default function Wordmark({ onHome }: { onHome?: () => void }) {
  return (
    <a
      className="wordmark"
      href="/"
      aria-label="pick&roll: all leagues"
      title="All leagues"
      onClick={(e) => {
        if (!onHome || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
        e.preventDefault();
        onHome();
      }}
    >
      PICK<span>&amp;</span>ROLL
    </a>
  );
}
