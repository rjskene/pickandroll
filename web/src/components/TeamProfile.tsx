import { CAT_LABEL, CATS, type Cat } from "../api";

interface Props {
  profile: { totals: Record<string, number>; punted: string[] } | null;
}

export default function TeamProfile({ profile }: Props) {
  return (
    <section className="panel">
      <span className="k">Expected team profile</span>
      {!profile ? (
        <p className="muted" style={{ margin: "8px 0 0" }}>
          Appears after the first solve.
        </p>
      ) : (
        <>
          <div className="profile" style={{ marginTop: 8 }}>
            {CATS.map((c: Cat) => {
              const v = profile.totals[c] ?? 0;
              const punted = profile.punted.includes(c);
              const width = Math.min(100, Math.max(2, (v + 20) * 2));
              return (
                <div key={c} className={`row ${punted ? "punted" : ""}`}>
                  <span className="lbl">{CAT_LABEL[c]}</span>
                  <div className="bar" style={{ flexGrow: 1 }}>
                    <span className={v < 0 ? "bad" : ""} style={{ width: `${width}%` }} />
                  </div>
                  <span className="val">{v.toFixed(1)}</span>
                </div>
              );
            })}
          </div>
          <p className="muted" style={{ margin: "8px 0 0", fontSize: 11 }}>
            Dimmed rows are punted. Bars are expected z totals if the plan holds.
          </p>
        </>
      )}
    </section>
  );
}
