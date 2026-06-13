"""Оркестратор: video.mov -> edl.json (план монтажа со субтитрами).

    python -m editor.build_edl samples/video1.mov --out output/video1.edl.json

Кэширует транскрипт рядом с EDL (<out>.segments.json), чтобы при отладке не
гонять whisper повторно (--fresh — пересчитать).
"""
import argparse
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from pipeline.transcribe import transcribe_segments
from .probe import probe
from .beats import build_beats
from .vision import analyze_beats
from .brain import build_edl
from .captions import attach_captions
from .translate import translate_captions
from .layout import resolve_collisions, verify


def _load_or_transcribe(video_path: str, cache_path: str, language, fresh: bool) -> list[dict]:
    if not fresh and os.path.isfile(cache_path):
        print(f"[edl] Беру транскрипт из кэша: {cache_path}")
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)
    segments = transcribe_segments(video_path, language)
    os.makedirs(os.path.dirname(os.path.abspath(cache_path)), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)
    return segments


def make_edl(video_path: str, out_path: str, language=None, target_language="ru",
             target_min=22.0, target_max=38.0, fresh=False, workdir=None,
             translate_to=None) -> dict:
    workdir = workdir or os.path.join(os.path.dirname(os.path.abspath(out_path)) or ".",
                                      "_edl_" + os.path.splitext(os.path.basename(video_path))[0])
    frames_dir = os.path.join(workdir, "beats")
    seg_cache = os.path.splitext(out_path)[0] + ".segments.json"

    print("[edl] 1/5 probe")
    meta = probe(video_path)
    print(f"      {meta}")

    print("[edl] 2/5 транскрипт")
    segments = _load_or_transcribe(video_path, seg_cache, language, fresh)
    print(f"      сегментов: {len(segments)}")

    print("[edl] 3/5 биты + качество кадров")
    beats = build_beats(video_path, segments, frames_dir)

    print("[edl] 4/5 vision-анализ")
    beats = analyze_beats(beats)

    print("[edl] 5/5 мозг -> EDL")
    edl = build_edl(beats, meta, target_language=target_language,
                    target_min=target_min, target_max=target_max)
    edl = attach_captions(edl, segments)

    if translate_to:
        print(f"[edl] перевод субтитров -> {translate_to}")
        edl = translate_captions(edl, translate_to)

    print("[edl] проверка наложений (layout)")
    edl, report = resolve_collisions(edl)
    for line in report:
        print(f"      • {line}")
    issues = verify(edl)
    if issues:
        for line in issues:
            print(f"      ! ОСТАЛОСЬ: {line}")
    else:
        print("      перекрытий не осталось")

    edl["source"] = os.path.abspath(video_path)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(edl, f, ensure_ascii=False, indent=2)
    print(f"[edl] Готово -> {out_path}")
    _print_summary(edl)
    return edl


def _print_summary(edl: dict) -> None:
    print("\n=== EDL summary ===")
    if edl["intro"].get("title"):
        print(f"INTRO: {edl['intro']['title']} / {edl['intro'].get('subtitle','')}")
    total = 0.0
    for i, c in enumerate(edl["clips"]):
        dur = c["src_end"] - c["src_start"]
        total += dur
        fx = ", ".join(
            (f"label:'{e['text']}'" if e["type"] == "label" else e["type"]) for e in c["effects"]
        ) or "—"
        cap = " | ".join(x["text"] for x in c.get("captions", []))[:70]
        print(f"  #{i:02d} [{c['src_start']:>5.1f}-{c['src_end']:>5.1f}] "
              f"{c['transition_in']:<9} fx:[{fx}]  «{cap}»")
    if edl["outro"].get("cta"):
        print(f"OUTRO: {edl['outro']['cta']}")
    print(f"TOTAL kept: ~{total:.1f}s, clips: {len(edl['clips'])}")


def main():
    ap = argparse.ArgumentParser(description="Собрать EDL (план автомонтажа) из видео")
    ap.add_argument("video")
    ap.add_argument("--out", default=None, help="куда писать edl.json")
    ap.add_argument("--lang", default=None, help="язык исходного аудио (whisper), напр. ru")
    ap.add_argument("--label-lang", default="ru", help="язык подписей/интро/аутро")
    ap.add_argument("--translate-to", default=None, help="перевести субтитры на этот язык")
    ap.add_argument("--min", type=float, default=22.0, help="минимальная длина результата, с")
    ap.add_argument("--max", type=float, default=38.0, help="максимальная длина результата, с")
    ap.add_argument("--fresh", action="store_true", help="пересчитать транскрипт (игнорировать кэш)")
    args = ap.parse_args()

    out = args.out or os.path.join(
        "output", os.path.splitext(os.path.basename(args.video))[0] + ".edl.json"
    )
    make_edl(args.video, out, language=args.lang, target_language=args.label_lang,
             target_min=args.min, target_max=args.max, fresh=args.fresh,
             translate_to=args.translate_to)


if __name__ == "__main__":
    main()
