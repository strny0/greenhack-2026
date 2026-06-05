export default function Legend() {
  return (
    <div className="legend">
      <h4>Line loading</h4>
      <div className="row">
        <span className="swatch" style={{ background: "linear-gradient(90deg,#2ecc71,#9acd32,#f5b915,#ff7a45,#ff4d4f)" }} />
        <span>0% → 110%+</span>
      </div>
      <h4 style={{ marginTop: 8 }}>Nodes</h4>
      <div className="row"><span className="dot" style={{ background: "#2f81f7" }} /> Generation</div>
      <div className="row"><span className="dot" style={{ background: "#e8833a" }} /> Load</div>
      <div className="row"><span className="dot" style={{ background: "#b07cff" }} /> Slack / ext. grid</div>
      <div className="row"><span className="dot" style={{ background: "#6b7a90" }} /> Substation</div>
      <div className="row"><span className="dot" style={{ background: "#1a2233", border: "2px solid #ff4d4f" }} /> Voltage alert ring</div>
    </div>
  );
}
