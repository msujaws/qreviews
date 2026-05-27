const INK = "var(--pt-ink)";
const MUTED = "var(--pt-muted)";
const FLAME = "var(--pt-flame)";
const SURFACE = "var(--pt-surface)";
const HAIRLINE = "color-mix(in srgb, var(--pt-ink) 22%, transparent)";

const VIEW_W = 820;
const VIEW_H = 400;

const FONT_MONO = "'IBM Plex Mono', ui-monospace, monospace";

type BoxProps = {
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
  sub?: string;
  faded?: boolean;
};

function Box({ x, y, w, h, label, sub, faded }: BoxProps) {
  const cx = x + w / 2;
  const labelY = sub ? y + h / 2 - 3 : y + h / 2 + 4;
  const subY = y + h / 2 + 13;
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx={3}
        ry={3}
        fill={SURFACE}
        stroke={faded ? HAIRLINE : MUTED}
        strokeWidth={1}
      />
      <text
        x={cx}
        y={labelY}
        textAnchor="middle"
        dominantBaseline="middle"
        fontFamily={FONT_MONO}
        fontSize={12}
        fontWeight={500}
        fill={faded ? MUTED : INK}
      >
        {label}
      </text>
      {sub && (
        <text
          x={cx}
          y={subY}
          textAnchor="middle"
          dominantBaseline="middle"
          fontFamily={FONT_MONO}
          fontSize={9}
          letterSpacing="0.14em"
          fill={MUTED}
        >
          {sub.toUpperCase()}
        </text>
      )}
    </g>
  );
}

type EdgeProps = {
  points: Array<[number, number]>;
  label?: string;
  labelPos?: [number, number];
  flame?: boolean;
};

function Edge({ points, label, labelPos, flame }: EdgeProps) {
  const d = points
    .map(([px, py], i) => (i === 0 ? `M${px},${py}` : `L${px},${py}`))
    .join(" ");
  const stroke = flame ? FLAME : MUTED;
  const marker = flame ? "url(#qr-arrow-flame)" : "url(#qr-arrow)";
  return (
    <g>
      <path
        d={d}
        fill="none"
        stroke={stroke}
        strokeWidth={1.25}
        markerEnd={marker}
      />
      {label && labelPos && (
        <text
          x={labelPos[0]}
          y={labelPos[1]}
          textAnchor="middle"
          dominantBaseline="middle"
          fontFamily={FONT_MONO}
          fontSize={9}
          letterSpacing="0.14em"
          fill={flame ? FLAME : MUTED}
        >
          {label.toUpperCase()}
        </text>
      )}
    </g>
  );
}

export function PipelineDiagram() {
  return (
    <div className="w-full">
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        width="100%"
        height="auto"
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label="qreviews pipeline diagram: Phabricator revisions flow through poller, scoring, gating, review, and posting back to Phabricator. Every step persists to SQLite, which the dashboard reads."
        style={{ display: "block", maxHeight: 460 }}
      >
        <defs>
          <marker
            id="qr-arrow"
            viewBox="0 0 10 10"
            refX={9}
            refY={5}
            markerWidth={7}
            markerHeight={7}
            orient="auto"
          >
            <path d="M0,0 L10,5 L0,10 z" fill={MUTED} />
          </marker>
          <marker
            id="qr-arrow-flame"
            viewBox="0 0 10 10"
            refX={9}
            refY={5}
            markerWidth={7}
            markerHeight={7}
            orient="auto"
          >
            <path d="M0,0 L10,5 L0,10 z" fill={FLAME} />
          </marker>
        </defs>

        {/* Phabricator (tall, left) */}
        <Box x={20} y={30} w={110} h={240} label="Phabricator" sub="conduit api" />

        {/* Row 1: Poller, Score, Skip */}
        <Box x={170} y={40} w={120} h={44} label="Poller" sub="hourly" />
        <Box x={330} y={40} w={150} h={44} label="Score" sub="claude haiku" />
        <Box x={520} y={40} w={120} h={44} label="Skip" sub="log only" faded />

        {/* Row 2: Review, Searchfox */}
        <Box x={330} y={140} w={150} h={44} label="Review" sub="claude sonnet" />
        <Box x={520} y={140} w={150} h={44} label="Searchfox" sub="mozilla-central" />

        {/* Row 3: Post */}
        <Box x={330} y={240} w={150} h={44} label="Post" sub="comment txn" />

        {/* Row 4: SQLite, Dashboard */}
        <Box x={330} y={330} w={150} h={44} label="SQLite" sub="state + metrics" />
        <Box x={520} y={330} w={150} h={44} label="Dashboard" sub="fastapi + react" />

        {/* Phab → Poller */}
        <Edge
          points={[
            [130, 62],
            [170, 62],
          ]}
          label="search"
          labelPos={[150, 54]}
        />

        {/* Poller → Score */}
        <Edge
          points={[
            [290, 62],
            [330, 62],
          ]}
        />

        {/* Score → Skip */}
        <Edge
          points={[
            [480, 62],
            [520, 62],
          ]}
          label="otherwise"
          labelPos={[500, 54]}
        />

        {/* Score → Review (flame, gate pass) */}
        <Edge
          points={[
            [405, 84],
            [405, 140],
          ]}
          label="both < threshold"
          labelPos={[460, 112]}
          flame
        />

        {/* Review → Searchfox (tools, bidirectional pair) */}
        <Edge
          points={[
            [480, 158],
            [520, 158],
          ]}
          label="tools"
          labelPos={[500, 134]}
        />
        <Edge
          points={[
            [520, 168],
            [480, 168],
          ]}
        />

        {/* Review → Post */}
        <Edge
          points={[
            [405, 184],
            [405, 240],
          ]}
        />

        {/* Post → SQLite */}
        <Edge
          points={[
            [405, 284],
            [405, 330],
          ]}
        />

        {/* SQLite → Dashboard */}
        <Edge
          points={[
            [480, 352],
            [520, 352],
          ]}
        />

        {/* Post → Phabricator (comment, loopback up the left side) */}
        <Edge
          points={[
            [330, 262],
            [150, 262],
            [150, 230],
            [130, 230],
          ]}
          label="comment"
          labelPos={[200, 254]}
        />
      </svg>
    </div>
  );
}
