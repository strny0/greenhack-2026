export default function Legend() {
  return (
    <div className="absolute left-3 top-3 z-10 max-w-[220px] rounded-lg border bg-card/90 p-3 text-[11px] shadow-md backdrop-blur">
      <h4 className="mb-1.5 text-[11px] uppercase text-muted-foreground">Line loading</h4>
      <div className="my-1 flex items-center gap-2">
        <span
          className="h-1 w-[22px] rounded-sm"
          style={{ background: "linear-gradient(90deg,#2ecc71,#9acd32,#f5b915,#ff7a45,#ff4d4f)" }}
        />
        <span>0% → 110%+</span>
      </div>
      <h4 className="mb-1.5 mt-2 text-[11px] uppercase text-muted-foreground">Nodes</h4>
      {[
        ["#2f81f7", "Generation"],
        ["#e8833a", "Load"],
        ["#b07cff", "Slack / ext. grid"],
        ["#6b7a90", "Substation"],
      ].map(([c, label]) => (
        <div key={label} className="my-1 flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: c }} />
          {label}
        </div>
      ))}
      <div className="my-1 flex items-center gap-2">
        <span
          className="h-2.5 w-2.5 rounded-full"
          style={{ background: "#1a2233", border: "2px solid #ff4d4f" }}
        />
        Voltage alert ring
      </div>
    </div>
  );
}
