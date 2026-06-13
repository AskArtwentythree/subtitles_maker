"""Генератор HyperFrames-композиции (HTML) из EDL.

Каждый клип EDL -> отдельный <video> с обрезкой источника (data-media-start +
data-duration), клипы встык на одном треке (жёсткие склейки). Зумы, плашки,
выделения, субтитры, интро/аутро и «дип» на переходах рисуем GSAP-таймлайном по
абсолютному времени. На выходе hf-effects/auto.html — рендер:

    npx hyperframes render hf-effects/auto.html --output output/video1_hf.mp4
"""
import argparse
import json
import os
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

ACCENT = "#7CF6C9"
INTRO_SEC = 1.4
OUTRO_SEC = 1.8


def _abs_clips(edl: dict) -> tuple[list[dict], float]:
    """Развернуть клипы в абсолютный таймлайн (жёсткие склейки, без перекрытий)."""
    out = []
    t = 0.0
    for i, c in enumerate(edl["clips"]):
        dur = round(c["src_end"] - c["src_start"], 3)
        zoom = next((e for e in c["effects"] if e["type"] == "zoom"), None)
        label = next((e for e in c["effects"] if e["type"] == "label"), None)
        hi = next((e for e in c["effects"] if e["type"] == "highlight"), None)
        caps = [{"text": x["text"], "start": round(t + x["start"], 3),
                 "end": round(t + x["end"], 3)} for x in c.get("captions", [])]
        out.append({
            "i": i,
            "start": round(t, 3),
            "dur": dur,
            "src_start": c["src_start"],
            "transition": c["transition_in"],
            "zoom": zoom,
            "label": label,
            "highlight": hi,
            "captions": caps,
            "origin": (f"{int(zoom['focus'][0]*100)}% {int(zoom['focus'][1]*100)}%"
                       if zoom else "50% 45%"),
        })
        t += dur
    return out, round(t, 3)


def build_html(edl: dict, video_file: str) -> str:
    clips, total = _abs_clips(edl)
    intro = edl.get("intro") or {}
    outro = edl.get("outro") or {}

    # Видео-клипы (track 0) — реальный DOM, HF их парсит.
    video_tags = []
    for c in clips:
        video_tags.append(
            f'<video class="clip" id="v{c["i"]}" src="{video_file}" playsinline '
            f'data-start="{c["start"]}" data-duration="{c["dur"]}" '
            f'data-media-start="{c["src_start"]}" data-track-index="0" '
            f'data-has-audio="true" data-volume="1" '
            f'style="transform-origin:{c["origin"]}"></video>'
        )
    videos_html = "\n      ".join(video_tags)

    payload = json.dumps({
        "clips": clips,
        "total": total,
        "intro": {"title": intro.get("title", ""), "subtitle": intro.get("subtitle", "")},
        "outro": {"cta": outro.get("cta", "")},
        "introSec": edl.get("intro_sec", INTRO_SEC),
        "outroSec": edl.get("outro_sec", OUTRO_SEC),
        "accent": ACCENT,
    }, ensure_ascii=False)

    return _TEMPLATE.replace("/*__EDL__*/", payload) \
        .replace("__TOTAL__", str(total)) \
        .replace("<!--__VIDEOS__-->", videos_html)


_TEMPLATE = r"""<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@700;800;900&display=swap" rel="stylesheet" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { width: 1080px; height: 1920px; overflow: hidden; background: #000; }
      body { font-family: "Montserrat", sans-serif; }
      video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; will-change: transform; }
      #scrim { position: absolute; inset: 0; pointer-events: none;
        background:
          linear-gradient(to bottom, rgba(0,0,0,0.4) 0%, rgba(0,0,0,0) 20%),
          linear-gradient(to top, rgba(0,0,0,0.6) 0%, rgba(0,0,0,0) 32%); }
      #captions, #overlays, #trans, #intro, #outro { position: absolute; inset: 0; }
      #trans { background: #000; opacity: 0; pointer-events: none; }
      .cap { position: absolute; left: 70px; right: 70px; bottom: 360px; text-align: center;
        opacity: 0; visibility: hidden; font-size: 52px; font-weight: 800; line-height: 1.18;
        color: #fff; text-shadow: 0 6px 24px rgba(0,0,0,0.6); -webkit-text-stroke: 1.5px rgba(0,0,0,0.4); }
      .label { position: absolute; left: 0; right: 0; display: flex; justify-content: center;
        opacity: 0; visibility: hidden; }
      .label .chip { background: var(--accent); color: #06251c; font-size: 40px; font-weight: 900;
        padding: 16px 30px; border-radius: 18px; max-width: 620px; text-align: center;
        box-shadow: 0 12px 36px rgba(0,0,0,0.4); }
      .label.top { top: 150px; } .label.center { top: 44%; } .label.bottom { bottom: 470px; }
      .ring { position: absolute; width: 280px; height: 280px; margin-left: -140px; margin-top: -140px;
        border-radius: 50%; border: 6px solid var(--accent); box-shadow: 0 0 30px var(--accent);
        opacity: 0; visibility: hidden; }
      #intro-inner { position: absolute; inset: 0; display: flex; flex-direction: column;
        align-items: center; justify-content: center; gap: 18px; background: rgba(0,0,0,0.92); }
      #intro .kicker { font-size: 30px; font-weight: 700; letter-spacing: 5px; color: var(--accent); text-transform: uppercase; }
      #intro .title { font-size: 96px; font-weight: 900; color: #fff; text-align: center; line-height: 1.0;
        padding: 0 60px; text-shadow: 0 10px 40px rgba(0,0,0,0.5); }
      #outro { display: flex; justify-content: center; align-items: flex-end; }
      #outro .pill { margin-bottom: 240px; background: var(--accent); color: #06251c; font-size: 48px;
        font-weight: 900; padding: 26px 52px; border-radius: 999px; max-width: 640px; text-align: center;
        opacity: 0; visibility: hidden; box-shadow: 0 18px 50px rgba(0,0,0,0.45); }
      :root { --accent: #7CF6C9; }
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="__TOTAL__"
         data-width="1080" data-height="1920">
      <!--__VIDEOS__-->
      <div id="scrim" class="clip" data-start="0" data-duration="__TOTAL__" data-track-index="1"></div>
      <div id="captions" class="clip" data-start="0" data-duration="__TOTAL__" data-track-index="2"></div>
      <div id="overlays" class="clip" data-start="0" data-duration="__TOTAL__" data-track-index="3"></div>
      <div id="trans" class="clip" data-start="0" data-duration="__TOTAL__" data-track-index="4"></div>
      <div id="intro" class="clip" data-start="0" data-duration="1.8" data-track-index="5">
        <div id="intro-inner"></div>
      </div>
      <div id="outro" class="clip" data-start="0" data-duration="__TOTAL__" data-track-index="6">
        <div class="pill"></div>
      </div>
    </div>

    <script>
      const EDL = /*__EDL__*/;
      document.documentElement.style.setProperty("--accent", EDL.accent);

      window.__timelines = window.__timelines || {};
      const tl = gsap.timeline({ paused: true });

      // --- Зум-пунши (ken-burns) на каждом клипе с эффектом zoom ---
      EDL.clips.forEach(function (c) {
        if (c.zoom) {
          tl.fromTo("#v" + c.i, { scale: 1.0 }, { scale: c.zoom.to, duration: c.dur, ease: "none" }, c.start);
        }
      });

      // --- Субтитры ---
      const capRoot = document.getElementById("captions");
      EDL.clips.forEach(function (c) {
        c.captions.forEach(function (g) {
          const el = document.createElement("div");
          el.className = "cap";
          el.textContent = g.text;
          capRoot.appendChild(el);
          const dur = Math.max(0.4, g.end - g.start);
          tl.set(el, { visibility: "visible" }, g.start);
          tl.fromTo(el, { opacity: 0, y: 34, scale: 0.94 }, { opacity: 1, y: 0, scale: 1, duration: 0.28, ease: "back.out(1.5)" }, g.start);
          tl.to(el, { opacity: 0, duration: 0.18, ease: "power2.in" }, g.end - 0.18);
          tl.set(el, { visibility: "hidden" }, g.end);
        });
      });

      // --- Плашки-подписи (label) ---
      const ovRoot = document.getElementById("overlays");
      EDL.clips.forEach(function (c) {
        if (!c.label) return;
        const wrap = document.createElement("div");
        wrap.className = "label " + (c.label.position || "top");
        const chip = document.createElement("div");
        chip.className = "chip";
        chip.textContent = c.label.text;
        wrap.appendChild(chip);
        ovRoot.appendChild(wrap);
        const a = c.start, b = c.start + c.dur;
        tl.set(wrap, { visibility: "visible" }, a + 0.1);
        tl.fromTo(wrap, { opacity: 0, y: 28 }, { opacity: 1, y: 0, duration: 0.35, ease: "back.out(1.5)" }, a + 0.15);
        tl.to(wrap, { opacity: 0, duration: 0.3, ease: "power2.in" }, b - 0.4);
        tl.set(wrap, { visibility: "hidden" }, b);
      });

      // --- Выделения-кольца (highlight) ---
      EDL.clips.forEach(function (c) {
        if (!c.highlight) return;
        const ring = document.createElement("div");
        ring.className = "ring";
        ring.style.left = (c.highlight.focus[0] * 100) + "%";
        ring.style.top = (c.highlight.focus[1] * 100) + "%";
        ovRoot.appendChild(ring);
        const a = c.start, b = c.start + c.dur;
        tl.set(ring, { visibility: "visible" }, a + 0.2);
        tl.fromTo(ring, { opacity: 0, scale: 1.25 }, { opacity: 0.9, scale: 1, duration: 0.4, ease: "power2.out" }, a + 0.2);
        tl.to(ring, { scale: 1.06, duration: 0.6, yoyo: true, repeat: Math.max(1, Math.floor((b - a) / 0.6)), ease: "sine.inOut" }, a + 0.6);
        tl.to(ring, { opacity: 0, duration: 0.3 }, b - 0.3);
        tl.set(ring, { visibility: "hidden" }, b);
      });

      // --- «Дип» на переходах (быстрое затемнение/мигание на склейке) ---
      EDL.clips.forEach(function (c) {
        if (c.i === 0 || c.transition === "none") return;
        const t = c.start;
        const white = c.transition === "zoom_blur";
        const peak = white ? 0.7 : 0.55;
        const tr = document.getElementById("trans");
        tl.set(tr, { backgroundColor: white ? "#fff" : "#000" }, t - 0.18);
        tl.to(tr, { opacity: peak, duration: 0.16, ease: "power2.out" }, t - 0.16);
        tl.to(tr, { opacity: 0, duration: 0.2, ease: "power2.in" }, t + 0.02);
      });

      // --- Интро ---
      const innerHtml = [];
      if (EDL.intro.subtitle) innerHtml.push('<div class="kicker">' + EDL.intro.subtitle + "</div>");
      if (EDL.intro.title) innerHtml.push('<div class="title">' + EDL.intro.title + "</div>");
      document.getElementById("intro-inner").innerHTML = innerHtml.join("");
      tl.from("#intro .kicker", { opacity: 0, y: 24, duration: 0.4, ease: "power3.out" }, 0.1);
      tl.from("#intro .title", { opacity: 0, scale: 0.82, duration: 0.5, ease: "back.out(1.6)" }, 0.15);
      tl.to("#intro-inner", { opacity: 0, duration: 0.35, ease: "power2.in" }, EDL.introSec);

      // --- Аутро-CTA ---
      if (EDL.outro.cta) {
        const pill = document.querySelector("#outro .pill");
        pill.textContent = EDL.outro.cta;
        const t = EDL.total - EDL.outroSec;
        tl.set(pill, { visibility: "visible" }, t);
        tl.fromTo(pill, { opacity: 0, y: 40 }, { opacity: 1, y: 0, duration: 0.45, ease: "back.out(1.6)" }, t);
      }

      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="EDL -> HyperFrames HTML")
    ap.add_argument("edl", help="путь к edl.json")
    ap.add_argument("--out", default="hf-effects/auto.html")
    args = ap.parse_args()

    with open(args.edl, encoding="utf-8") as f:
        edl = json.load(f)

    src = edl.get("source")
    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    # Уникальное имя источника на каждый EDL — чтобы несколько композиций в одной
    # папке не перетирали друг другу видео.
    stem = os.path.splitext(os.path.basename(args.edl))[0].replace(".edl", "")
    video_file = f"src_{stem}.mp4"
    if src and os.path.isfile(src):
        shutil.copy(src, os.path.join(out_dir, video_file))
    else:
        print(f"[hf] ВНИМАНИЕ: исходник {src} не найден, ожидаю {video_file} рядом с html")

    html = build_html(edl, video_file)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[hf] HTML готов -> {args.out}")
    print(f"[hf] Рендер: npx hyperframes render {args.out} --output output/{os.path.splitext(os.path.basename(args.edl))[0]}_hf.mp4")


if __name__ == "__main__":
    main()
