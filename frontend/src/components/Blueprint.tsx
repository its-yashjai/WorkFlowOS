/** Blueprint grid with data packets flowing along it: the "work moving by itself" motif. */
const PACKETS = [
  { top: "18%", dur: 9, delay: 0 }, { top: "46%", dur: 13, delay: 3 }, { top: "72%", dur: 11, delay: 6 },
];
const VPACKETS = [{ left: "22%", dur: 12, delay: 2 }, { left: "68%", dur: 15, delay: 7 }];
export default function Blueprint() {
  return (
    <div className="blueprint" aria-hidden>
      <div className="glow g1" />
      <div className="glow g2" />
      <div className="grid" />
      {PACKETS.map((p, i) => <span key={i} className="packet" style={{ top: p.top, animationDuration: `${p.dur}s`, animationDelay: `${p.delay}s` }} />)}
      {VPACKETS.map((p, i) => <span key={i} className="packet v" style={{ left: p.left, animationDuration: `${p.dur}s`, animationDelay: `${p.delay}s` }} />)}
    </div>
  );
}
