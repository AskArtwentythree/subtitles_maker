"""Рендер Remotion-композиции AutoEdit из EDL (параметризованный вход).

Копирует исходник в my-video/public, пишет props ({edl:{...,videoFile}}) и
запускает `npx remotion render` с этим props. Так один и тот же проект Remotion
рендерит любой ролик без правок кода.

    python -m editor.render_remotion output/video2.edl.json --out output/video2_remotion.mp4
"""
import argparse
import json
import os
import shutil
import subprocess
import sys


def _browser_executable() -> str | None:
    """Найти Chromium для Remotion.

    Локально (Windows) вернём None — Remotion возьмёт свой скачанный Chrome.
    На сервере (Railway/Nix) ставим системный chromium и указываем его явно,
    чтобы Remotion не качал headless-shell и не упирался в отсутствующие либы.
    """
    env = os.environ.get("REMOTION_BROWSER_EXECUTABLE")
    if env:
        return env
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        path = shutil.which(name)
        if path:
            return path
    return None

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT = os.path.join(ROOT, "my-video")
PUBLIC = os.path.join(PROJECT, "public")


COMPOSITIONS = {"a": "AutoEdit", "b": "AutoEditB"}


def render(edl_path: str, out_path: str, style: str = "a") -> str:
    with open(edl_path, encoding="utf-8") as f:
        edl = json.load(f)

    src = edl.get("source")
    if not src or not os.path.isfile(src):
        raise FileNotFoundError(f"Исходник не найден: {src}")

    os.makedirs(PUBLIC, exist_ok=True)
    video_file = "src_" + os.path.splitext(os.path.basename(edl_path))[0].replace(".edl", "") + os.path.splitext(src)[1].lower()
    shutil.copy(src, os.path.join(PUBLIC, video_file))

    edl["videoFile"] = video_file
    props = {"edl": edl, "styleId": style}
    # Имя props привязываем к конкретной задаче (basename EDL) + стилю, иначе при
    # параллельной обработке двух видео файлы _props_a.json затирают друг друга,
    # и Remotion читает чужой EDL (битый рендер / зависание).
    job = os.path.splitext(os.path.basename(edl_path))[0].replace(".edl", "")
    props_path = os.path.join(PROJECT, f"_props_{job}_{style}.json")
    with open(props_path, "w", encoding="utf-8") as f:
        json.dump(props, f, ensure_ascii=False)

    out_abs = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_abs) or ".", exist_ok=True)

    comp = COMPOSITIONS.get(style, "AutoEdit")
    print(f"[remotion] рендер {video_file} (style={style}, comp={comp}) -> {out_abs}")
    cmd = f'npx remotion render {comp} "{out_abs}" "--props={props_path}" --timeout=120000'

    # «Серверность» определяем по ОС, а НЕ по наличию chromium: иначе, если
    # chromium не нашёлся на PATH, отключались все лимиты памяти и Remotion брал
    # параллельность по числу ядер (4x) -> OOM (compositor SIGKILL под конец).
    on_server = os.name != "nt"

    browser = _browser_executable()
    if browser:
        cmd += f' "--browser-executable={browser}"'

    # Память — главный лимит в контейнере. Каждая параллельная вкладка Chromium
    # рендерит кадр 1080x1920 и ест сотни МБ; при дефолтной параллельности (по
    # числу ядер) контейнер ловит OOM (exit 137 / "Page crashed").
    # На сервере (нашли системный chromium) принудительно ставим минимум, а
    # значения при желании переопределяются переменными окружения.
    concurrency = os.environ.get("REMOTION_CONCURRENCY") or ("1" if on_server else None)
    if concurrency:
        cmd += f" --concurrency={concurrency}"

    # Даунскейл итогового кадра тоже режет память (рендерим в меньшем разрешении,
    # раскладка остаётся пропорциональной). 0.6667 от 1080x1920 = 720x1280 —
    # для шортса нормально (платформы всё равно пережимают).
    scale = os.environ.get("REMOTION_SCALE") or ("0.6667" if on_server else None)
    if scale:
        cmd += f" --scale={scale}"

    # CRF: чем выше — тем меньше файл (и быстрее аплоад в Telegram). Эффекты вроде
    # киноплёнки/зерна дают шумный кадр и раздувают h264 — на сервере поджимаем
    # сильнее (28), чтобы ролик влезал в лимит и не вис на отправке.
    crf = os.environ.get("REMOTION_CRF") or ("28" if on_server else None)
    if crf:
        cmd += f" --crf={crf}"

    # Кэш декодированных кадров OffthreadVideo по умолчанию растёт почти без предела
    # и к концу ролика забивает память -> compositor падает по SIGKILL под самый
    # конец рендера. Ограничиваем его на сервере (256 МБ достаточно для шортса).
    cache = os.environ.get("REMOTION_OFFTHREAD_CACHE") or ("268435456" if on_server else None)
    if cache:
        cmd += f" --offthreadvideo-cache-size-in-bytes={cache}"

    # Стримим вывод (видно прогресс в логах Railway) и одновременно держим хвост,
    # чтобы при падении положить реальную причину в исключение -> сообщение в Telegram.
    import collections

    tail: collections.deque[str] = collections.deque(maxlen=40)
    try:
        proc = subprocess.Popen(
            cmd, cwd=PROJECT, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            tail.append(line.rstrip("\n"))
        proc.wait()
        if proc.returncode != 0:
            detail = "\n".join(tail)[-1200:]
            raise RuntimeError(f"remotion render завершился с кодом {proc.returncode}:\n{detail}")
    finally:
        # Чистим временные артефакты задачи (props + копию исходника в public),
        # чтобы они не накапливались и не пересекались с другими задачами.
        for p in (props_path, os.path.join(PUBLIC, video_file)):
            try:
                os.remove(p)
            except OSError:
                pass

    print(f"[remotion] готово -> {out_abs}")
    return out_abs


def main():
    ap = argparse.ArgumentParser(description="EDL -> Remotion MP4")
    ap.add_argument("edl")
    ap.add_argument("--out", default=None)
    ap.add_argument("--style", choices=["a", "b"], default="a", help="набор эффектов: a (Clean Mint) / b (Bold Pop)")
    args = ap.parse_args()
    suffix = "_remotion" if args.style == "a" else "_remotion_b"
    out = args.out or os.path.join(
        "output", os.path.splitext(os.path.basename(args.edl))[0].replace(".edl", "") + suffix + ".mp4"
    )
    render(args.edl, out, args.style)


if __name__ == "__main__":
    main()
