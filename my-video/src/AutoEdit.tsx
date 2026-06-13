import {
  AbsoluteFill,
  Img,
  OffthreadVideo,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  Sequence,
  Easing,
} from "remotion";
import {
  TransitionSeries,
  linearTiming,
  type TransitionPresentation,
} from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { slide } from "@remotion/transitions/slide";
import { wipe } from "@remotion/transitions/wipe";

// Локальный стек шрифтов — без сетевой загрузки Google Fonts,
// чтобы рендер не зависел от доступа к fonts.gstatic.com.
const fontFamily = "Montserrat, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif";

export type StyleId = "a" | "b";

// Две палитры/набора эффектов для сравнения.
const THEME = {
  a: { accent: "#7CF6C9", onAccent: "#06251c" },
  b: { accent: "#FFE14D", onAccent: "#10131A" },
} as const;

// ---- Типы EDL (совпадают с editor/brain.py) ----
export type Effect =
  | { type: "zoom"; to: number; focus: [number, number] }
  | { type: "label"; text: string; position: "top" | "center" | "bottom" }
  | { type: "highlight"; focus: [number, number] };

export type Caption = { text: string; start: number; end: number };

export type Clip = {
  src_start: number;
  src_end: number;
  transition_in: "none" | "fade" | "whip" | "slide" | "zoom_blur";
  transition_dur: number;
  effects: Effect[];
  captions: Caption[];
};

export type Edl = {
  intro: { title: string; subtitle: string };
  clips: Clip[];
  outro: { cta: string };
  meta: { width: number; height: number; fps: number; duration: number };
  target_language: string;
  videoFile: string;
  intro_sec?: number;
  outro_sec?: number;
};

const INTRO_SEC_DEFAULT = 1.4;
const OUTRO_SEC_DEFAULT = 1.8;

export const clipFrames = (c: Clip, fps: number) =>
  Math.max(1, Math.round((c.src_end - c.src_start) * fps));

export const transitionFrames = (c: Clip, fps: number) =>
  c.transition_in === "none" ? 0 : Math.max(1, Math.round((c.transition_dur || 0.35) * fps));

export const totalFrames = (edl: Edl, fps: number) => {
  let sum = 0;
  edl.clips.forEach((c, i) => {
    sum += clipFrames(c, fps);
    if (i > 0) sum -= transitionFrames(c, fps);
  });
  return Math.max(1, sum);
};

const zoomFocus = (clip: Clip): [number, number] | null => {
  const z = clip.effects.find((e) => e.type === "zoom") as
    | Extract<Effect, { type: "zoom" }>
    | undefined;
  if (z) return z.focus;
  const h = clip.effects.find((e) => e.type === "highlight") as
    | Extract<Effect, { type: "highlight" }>
    | undefined;
  return h ? h.focus : null;
};

// =================== СУБТИТРЫ ===================
const Captions: React.FC<{ captions: Caption[]; fps: number; styleId: StyleId }> = ({
  captions,
  fps,
  styleId,
}) => {
  const frame = useCurrentFrame();
  const t = frame / fps;
  const accent = THEME[styleId].accent;

  return (
    <>
      {captions.map((c, i) => {
        if (t < c.start || t > c.end) return null;
        const inA = interpolate(t, [c.start, c.start + 0.28], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        const outA = interpolate(t, [c.end - 0.18, c.end], [1, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        const opacity = Math.min(inA, outA);
        const y = interpolate(t, [c.start, c.start + 0.28], [34, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });

        if (styleId === "a") {
          return (
            <div
              key={i}
              style={{
                position: "absolute",
                left: 70,
                right: 70,
                bottom: 360,
                textAlign: "center",
                fontSize: 52,
                fontWeight: 800,
                lineHeight: 1.18,
                color: "#fff",
                opacity,
                transform: `translateY(${y}px)`,
                textShadow: "0 6px 24px rgba(0,0,0,0.6)",
                WebkitTextStroke: "1.5px rgba(0,0,0,0.4)",
              }}
            >
              {c.text}
            </div>
          );
        }

        // Style B — компактная плашка в нижней трети (не лезет в центр кадра),
        // с жёлтым подчёркиванием.
        const bar = interpolate(t, [c.start + 0.1, c.start + 0.5], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        const scale = interpolate(inA, [0, 1], [0.9, 1]);
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: 80,
              right: 80,
              bottom: 210,
              display: "flex",
              justifyContent: "center",
              opacity,
              transform: `translateY(${y}px) scale(${scale})`,
            }}
          >
            <div
              style={{
                background: "rgba(10,13,16,0.72)",
                borderRadius: 16,
                padding: "12px 22px 15px",
                maxWidth: 720,
                textAlign: "center",
              }}
            >
              <div
                style={{
                  fontSize: 40,
                  fontWeight: 800,
                  lineHeight: 1.12,
                  color: "#fff",
                  textTransform: "uppercase",
                  letterSpacing: 0.3,
                }}
              >
                {c.text}
              </div>
              <div
                style={{
                  height: 6,
                  marginTop: 9,
                  borderRadius: 99,
                  background: accent,
                  transform: `scaleX(${bar})`,
                  transformOrigin: "left center",
                }}
              />
            </div>
          </div>
        );
      })}
    </>
  );
};

// =================== ПЛАШКА-ПОДПИСЬ ===================
const Label: React.FC<{
  fx: Extract<Effect, { type: "label" }>;
  dur: number;
  fps: number;
  styleId: StyleId;
}> = ({ fx, dur, fps, styleId }) => {
  const frame = useCurrentFrame();
  const t = frame / fps;
  const accent = THEME[styleId].accent;
  const onAccent = THEME[styleId].onAccent;

  const inA = interpolate(t, [0.15, 0.5], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const outA = interpolate(t, [dur - 0.4, dur - 0.1], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const opacity = Math.min(inA, outA);

  if (styleId === "a") {
    const pos =
      fx.position === "top" ? { top: 150 } : fx.position === "center" ? { top: "44%" as const } : { bottom: 470 };
    const y = interpolate(inA, [0, 1], [30, 0]);
    return (
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          display: "flex",
          justifyContent: "center",
          opacity,
          transform: `translateY(${y}px)`,
          ...pos,
        }}
      >
        <div
          style={{
            backgroundColor: accent,
            color: onAccent,
            fontSize: 40,
            fontWeight: 900,
            padding: "16px 30px",
            borderRadius: 18,
            letterSpacing: 0.5,
            boxShadow: "0 12px 36px rgba(0,0,0,0.4)",
            maxWidth: 620,
            textAlign: "center",
          }}
        >
          {fx.text}
        </div>
      </div>
    );
  }

  // Style B — стикер с наклоном и pop-анимацией
  const rot = interpolate(inA, [0, 1], [-11, -3]);
  const scale = interpolate(inA, [0, 1], [0.7, 1]);
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        top: 140,
        display: "flex",
        justifyContent: "center",
        opacity,
      }}
    >
      <div
        style={{
          backgroundColor: accent,
          color: onAccent,
          fontSize: 44,
          fontWeight: 900,
          padding: "16px 30px",
          borderRadius: 14,
          letterSpacing: 0.5,
          textTransform: "uppercase",
          boxShadow: "0 14px 40px rgba(0,0,0,0.5)",
          maxWidth: 640,
          textAlign: "center",
          transform: `rotate(${rot}deg) scale(${scale})`,
        }}
      >
        {fx.text}
      </div>
    </div>
  );
};

// =================== СТРЕЛКА К ПРОДУКТУ (Style B) ===================
const Arrow: React.FC<{ focus: [number, number]; fps: number; accent: string }> = ({
  focus,
  fps,
  accent,
}) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const t = frame / fps;

  const sx = width * 0.5;
  const sy = 250; // из-под плашки сверху
  const ex = focus[0] * width;
  const ey = Math.max(focus[1] * height - 150, 360); // чуть выше точки фокуса
  const cx = (sx + ex) / 2 + (ex > sx ? -120 : 120);
  const cy = (sy + ey) / 2;

  const draw = interpolate(t, [0.35, 0.85], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const opacity = interpolate(t, [0.3, 0.5], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  // Угол наконечника по касательной control->end
  const ang = Math.atan2(ey - cy, ex - cx);
  const ah = 34;
  const a1 = ang + Math.PI - 0.45;
  const a2 = ang + Math.PI + 0.45;
  const headVisible = draw > 0.85 ? 1 : 0;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      style={{ position: "absolute", inset: 0, pointerEvents: "none", opacity }}
    >
      <path
        d={`M ${sx} ${sy} Q ${cx} ${cy} ${ex} ${ey}`}
        fill="none"
        stroke={accent}
        strokeWidth={12}
        strokeLinecap="round"
        pathLength={1}
        strokeDasharray={1}
        strokeDashoffset={1 - draw}
        style={{ filter: "drop-shadow(0 4px 10px rgba(0,0,0,0.5))" }}
      />
      <g opacity={headVisible}>
        <line x1={ex} y1={ey} x2={ex + ah * Math.cos(a1)} y2={ey + ah * Math.sin(a1)} stroke={accent} strokeWidth={12} strokeLinecap="round" />
        <line x1={ex} y1={ey} x2={ex + ah * Math.cos(a2)} y2={ey + ah * Math.sin(a2)} stroke={accent} strokeWidth={12} strokeLinecap="round" />
      </g>
    </svg>
  );
};

// =================== ВЫДЕЛЕНИЕ-КОЛЬЦО ===================
const Highlight: React.FC<{ fx: Extract<Effect, { type: "highlight" }>; fps: number; accent: string }> = ({
  fx,
  fps,
  accent,
}) => {
  const frame = useCurrentFrame();
  const t = frame / fps;
  const pulse = 1 + 0.06 * Math.sin(t * Math.PI * 2.2);
  const appear = interpolate(t, [0.2, 0.6], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <div
      style={{
        position: "absolute",
        left: `${fx.focus[0] * 100}%`,
        top: `${fx.focus[1] * 100}%`,
        width: 280,
        height: 280,
        marginLeft: -140,
        marginTop: -140,
        borderRadius: "50%",
        border: `6px solid ${accent}`,
        boxShadow: `0 0 30px ${accent}`,
        opacity: appear * 0.9,
        transform: `scale(${pulse})`,
      }}
    />
  );
};

// =================== ВИНЬЕТКА + ЗЕРНО (Style B) ===================
// Зерно задаётся data-URI SVG с feTurbulence: картинка растеризуется ОДИН раз,
// поэтому композитинг дёшев на каждом кадре (в отличие от инлайнового <svg> фильтра,
// который пересчитывается покадрово и резко тормозит рендер).
const GRAIN_SRC =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(
    "<svg xmlns='http://www.w3.org/2000/svg' width='540' height='960'>" +
      "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/></filter>" +
      "<rect width='100%' height='100%' filter='url(#n)'/></svg>",
  );

const Cinematic: React.FC = () => (
  <>
    <AbsoluteFill
      style={{
        pointerEvents: "none",
        background: "radial-gradient(ellipse at center, rgba(0,0,0,0) 52%, rgba(0,0,0,0.55) 100%)",
      }}
    />
    <Img
      src={GRAIN_SRC}
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        objectFit: "cover",
        pointerEvents: "none",
        opacity: 0.07,
        mixBlendMode: "overlay",
      }}
    />
  </>
);

// =================== КЛИП ===================
const ClipView: React.FC<{ clip: Clip; videoFile: string; fps: number; styleId: StyleId }> = ({
  clip,
  videoFile,
  fps,
  styleId,
}) => {
  const frame = useCurrentFrame();
  const dur = clip.src_end - clip.src_start;
  const t = frame / fps;
  const accent = THEME[styleId].accent;

  const zoom = clip.effects.find((e) => e.type === "zoom") as
    | Extract<Effect, { type: "zoom" }>
    | undefined;

  let scale = 1;
  if (zoom) {
    if (styleId === "a") {
      // медленный ken-burns на всю длину
      scale = interpolate(t, [0, dur], [1.0, zoom.to], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
    } else {
      // панч-зум: быстро наезжает и слегка отпускает
      const punch = interpolate(t, [0, 0.4], [1.0, zoom.to + 0.03], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
        easing: Easing.out(Easing.cubic),
      });
      const settle = interpolate(t, [0.4, Math.max(dur, 0.8)], [zoom.to + 0.03, zoom.to], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
      scale = t < 0.4 ? punch : settle;
    }
  }
  const origin = zoom ? `${zoom.focus[0] * 100}% ${zoom.focus[1] * 100}%` : "50% 45%";

  const focus = zoomFocus(clip);
  const hasLabel = clip.effects.some((e) => e.type === "label");

  return (
    <AbsoluteFill style={{ backgroundColor: "#000", fontFamily }}>
      <AbsoluteFill style={{ transform: `scale(${scale})`, transformOrigin: origin }}>
        <OffthreadVideo
          src={staticFile(videoFile)}
          trimBefore={Math.round(clip.src_start * fps)}
          trimAfter={Math.round(clip.src_end * fps)}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
        />
      </AbsoluteFill>

      <AbsoluteFill
        style={{
          pointerEvents: "none",
          background:
            "linear-gradient(to bottom, rgba(0,0,0,0.4) 0%, rgba(0,0,0,0) 20%), linear-gradient(to top, rgba(0,0,0,0.6) 0%, rgba(0,0,0,0) 32%)",
        }}
      />

      {styleId === "b" ? <Cinematic /> : null}

      {clip.effects
        .filter((e) => e.type === "highlight")
        .map((e, i) => (
          <Highlight key={i} fx={e as Extract<Effect, { type: "highlight" }>} fps={fps} accent={accent} />
        ))}

      {/* Style B: стрелка к продукту, когда есть и подпись, и точка фокуса */}
      {styleId === "b" && hasLabel && focus ? <Arrow focus={focus} fps={fps} accent={accent} /> : null}

      {clip.effects
        .filter((e) => e.type === "label")
        .map((e, i) => (
          <Label key={i} fx={e as Extract<Effect, { type: "label" }>} dur={dur} fps={fps} styleId={styleId} />
        ))}

      <Captions captions={clip.captions} fps={fps} styleId={styleId} />
    </AbsoluteFill>
  );
};

// =================== ПЕРЕХОДЫ ===================
const presentationFor = (
  kind: Clip["transition_in"],
  styleId: StyleId,
): TransitionPresentation<Record<string, unknown>> => {
  const cast = (p: unknown) => p as TransitionPresentation<Record<string, unknown>>;
  // Только лёгкие CSS-переходы (slide/wipe/fade): они рендерятся быстро (как в
  // HyperFrames), в отличие от WebGL-шейдеров, которые без GPU считаются
  // программно и кратно замедляют рендер. Для Style B берём более «бодрые»
  // направления, чтобы переход ощущался динамичнее.
  if (styleId === "b") {
    switch (kind) {
      case "whip":
        return cast(slide({ direction: "from-right" }));
      case "slide":
        return cast(slide({ direction: "from-bottom" }));
      case "zoom_blur":
        return cast(wipe({ direction: "from-bottom-right" }));
      case "fade":
      default:
        return cast(fade());
    }
  }
  switch (kind) {
    case "whip":
      return cast(slide({ direction: "from-right" }));
    case "slide":
      return cast(slide({ direction: "from-bottom" }));
    case "zoom_blur":
      return cast(wipe({ direction: "from-bottom-right" }));
    case "fade":
    default:
      return cast(fade());
  }
};

// =================== ИНТРО / АУТРО ===================
const Overlays: React.FC<{ edl: Edl; styleId: StyleId }> = ({ edl, styleId }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const t = frame / fps;
  const end = durationInFrames / fps;
  const accent = THEME[styleId].accent;
  const onAccent = THEME[styleId].onAccent;

  const INTRO_SEC = edl.intro_sec ?? INTRO_SEC_DEFAULT;
  const OUTRO_SEC = edl.outro_sec ?? OUTRO_SEC_DEFAULT;

  const introOut = interpolate(t, [INTRO_SEC - 0.35, INTRO_SEC], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const outroIn = interpolate(t, [end - OUTRO_SEC, end - OUTRO_SEC + 0.4], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const showIntro = t < INTRO_SEC && edl.intro.title;
  const showOutro = t > end - OUTRO_SEC && edl.outro.cta;

  // ---- Style A ----
  if (styleId === "a") {
    const introTitle = interpolate(t, [0.1, 0.6], [0.82, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
    return (
      <>
        {showIntro ? (
          <AbsoluteFill
            style={{
              opacity: introOut,
              background: "rgba(0,0,0,0.92)",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: 18,
              fontFamily,
            }}
          >
            {edl.intro.subtitle ? (
              <div style={{ fontSize: 30, fontWeight: 700, letterSpacing: 5, color: accent, textTransform: "uppercase" }}>
                {edl.intro.subtitle}
              </div>
            ) : null}
            <div
              style={{
                fontSize: 96,
                fontWeight: 900,
                color: "#fff",
                textAlign: "center",
                lineHeight: 1.0,
                padding: "0 60px",
                transform: `scale(${introTitle})`,
                textShadow: "0 10px 40px rgba(0,0,0,0.5)",
              }}
            >
              {edl.intro.title}
            </div>
          </AbsoluteFill>
        ) : null}

        {showOutro ? (
          <div
            style={{
              position: "absolute",
              left: 0,
              right: 0,
              bottom: 240,
              display: "flex",
              justifyContent: "center",
              opacity: outroIn,
              transform: `translateY(${interpolate(outroIn, [0, 1], [40, 0])}px)`,
              fontFamily,
            }}
          >
            <div
              style={{
                backgroundColor: accent,
                color: onAccent,
                fontSize: 48,
                fontWeight: 900,
                padding: "26px 52px",
                borderRadius: 999,
                textAlign: "center",
                maxWidth: 640,
                boxShadow: "0 18px 50px rgba(0,0,0,0.45)",
              }}
            >
              {edl.outro.cta}
            </div>
          </div>
        ) : null}
      </>
    );
  }

  // ---- Style B: кинетический слэм слов + нижний бар-CTA ----
  const words = (edl.intro.title || "").split(/\s+/).filter(Boolean);
  return (
    <>
      {showIntro ? (
        <AbsoluteFill
          style={{
            opacity: introOut,
            background: "rgba(10,13,16,0.93)",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 22,
            fontFamily,
          }}
        >
          {edl.intro.subtitle ? (
            <div style={{ fontSize: 32, fontWeight: 800, letterSpacing: 6, color: accent, textTransform: "uppercase" }}>
              {edl.intro.subtitle}
            </div>
          ) : null}
          <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: "0 22px", padding: "0 50px" }}>
            {words.map((w, i) => {
              const at = 0.1 + i * 0.12;
              const wIn = interpolate(t, [at, at + 0.32], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
              const sc = interpolate(wIn, [0, 1], [1.8, 1]);
              return (
                <span
                  key={i}
                  style={{
                    fontSize: 104,
                    fontWeight: 900,
                    color: "#fff",
                    textTransform: "uppercase",
                    lineHeight: 1.0,
                    opacity: wIn,
                    display: "inline-block",
                    transform: `scale(${sc})`,
                    textShadow: "0 10px 40px rgba(0,0,0,0.6)",
                  }}
                >
                  {w}
                </span>
              );
            })}
          </div>
        </AbsoluteFill>
      ) : null}

      {showOutro ? (
        <div
          style={{
            position: "absolute",
            left: 50,
            right: 50,
            bottom: 200,
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            gap: 18,
            background: accent,
            color: onAccent,
            fontSize: 50,
            fontWeight: 900,
            textTransform: "uppercase",
            padding: "30px 40px",
            borderRadius: 22,
            textAlign: "center",
            boxShadow: "0 20px 55px rgba(0,0,0,0.5)",
            opacity: outroIn,
            transform: `translateY(${interpolate(outroIn, [0, 1], [60, 0])}px)`,
            fontFamily,
          }}
        >
          {edl.outro.cta} <span style={{ fontSize: 56 }}>→</span>
        </div>
      ) : null}
    </>
  );
};

// =================== КОМПОЗИЦИЯ ===================
export const AutoEdit: React.FC<{ edl: Edl; styleId?: StyleId }> = ({ edl, styleId = "a" }) => {
  const { fps } = useVideoConfig();
  const videoFile = edl.videoFile || "video1.mov";

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      <TransitionSeries>
        {edl.clips.map((clip, i) => {
          const cf = clipFrames(clip, fps);
          const nodes = [];
          if (i > 0 && clip.transition_in !== "none") {
            nodes.push(
              <TransitionSeries.Transition
                key={`t-${i}`}
                presentation={presentationFor(clip.transition_in, styleId)}
                timing={linearTiming({ durationInFrames: transitionFrames(clip, fps) })}
              />,
            );
          }
          nodes.push(
            <TransitionSeries.Sequence key={`s-${i}`} durationInFrames={cf}>
              <ClipView clip={clip} videoFile={videoFile} fps={fps} styleId={styleId} />
            </TransitionSeries.Sequence>,
          );
          return nodes;
        })}
      </TransitionSeries>

      <Sequence>
        <Overlays edl={edl} styleId={styleId} />
      </Sequence>
    </AbsoluteFill>
  );
};
