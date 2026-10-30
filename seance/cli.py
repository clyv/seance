"""Command line for Séance."""

from __future__ import annotations

import argparse
import shutil
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from . import __version__
from .config import AUDIO_EXTENSIONS, Config, default_home, load_config, write_example_config
from .llm import OllamaError
from .render import fmt_duration
from .transcript import fmt_ts, parse_ts


def _out(text: str = "") -> None:
    print(text, flush=True)


def _reconfigure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def _app(cfg: Config):
    from .pipeline import Seance
    return Seance(cfg)


def _need_archive(cfg: Config) -> None:
    if not cfg.home.exists():
        raise SystemExit(f"No archive at {cfg.home}. Run `seance init` first.")


def _parse_date(text: str | None) -> datetime | None:
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise SystemExit(f"Couldn't read the date '{text}'. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM.")


# Output helpers ----------------------------------------------------------------

def print_story_card(story, *, header: str = "") -> None:
    c = story.card
    if header:
        _out(header)
    _out(f"🕯️  {story.title}  ({story.id})")
    meta = [story.speaker, f"recorded {story.recorded_date}"]
    if story.duration:
        meta.append(fmt_duration(story.duration))
    if story.language:
        meta.append(story.language)
    _out("    " + " · ".join(meta))
    if c.summary:
        _out(f"    {c.summary}")
    if c.moments:
        _out("")
        _out("    In their words:")
        for m in c.moments:
            ts = fmt_ts(m.start)
            _out(f"     {'[' + ts + '] ' if ts else ''}{m.heading}")
            _out(f"        “{m.quote}”")
    if c.people:
        _out("")
        _out("    People:  " + ", ".join(p["name"] + (f" ({p['relation']})" if p["relation"] else "") for p in c.people))
    if c.places:
        _out("    Places:  " + ", ".join(c.places))
    if c.years:
        _out("    When:    " + "; ".join(f"{y['when']}: {y['what']}" for y in c.years[:6]))
    if c.follow_up_questions:
        _out("")
        _out(f"    Ask {story.speaker} next time:")
        for q in c.follow_up_questions:
            _out(f"     · {q}")
    if c.dropped_quotes:
        _out("")
        _out(f"    ({c.dropped_quotes} suggested quote{'s' if c.dropped_quotes != 1 else ''} left out: "
             "not found in the recording)")


def _print_add(result, cfg: Config) -> None:
    s = result.story
    bits = [f"{result.words} words"]
    if s.duration and s.transcribe_seconds:
        bits.append(f"{fmt_duration(s.duration)} of audio transcribed in {s.transcribe_seconds:.1f}s")
    if s.translate_seconds:
        bits.append(f"translated in {s.translate_seconds:.1f}s")
    bits.append(f"Gemma took {s.card.model_seconds:.1f}s")
    _out(f"🎙️  {s.source_name}: " + " · ".join(bits))
    _out("")
    print_story_card(s)
    _out("")
    _out(f"📄 {cfg.stories_dir / (s.id + '.md')}")
    _out(f"✿  {cfg.home / 'ofrenda.html'}")
    if not result.embedded:
        _out("   (keyword search; `ollama pull embeddinggemma` then `seance reindex` for smarter search)")


# Commands ------------------------------------------------------------------------

def cmd_init(args, cfg: Config) -> int:
    home = Path(args.home).expanduser() if args.home else (cfg.home if cfg.source else default_home())
    cfg.home = home
    cfg.ensure_dirs()
    if cfg.config_path.exists() and not args.force:
        _out(f"Config already exists: {cfg.config_path}")
    else:
        write_example_config(home)
        _out(f"Wrote {cfg.config_path}")
    from .pipeline import Seance
    Seance(cfg).refresh()
    _out(f"Archive:   {home}")
    _out(f"Ofrenda:   {home / 'ofrenda.html'}")
    if args.home and Path(args.home).expanduser() != default_home():
        _out("")
        _out("This isn't the default location, so tell Séance where it is, either with")
        _out(f'  --config "{cfg.config_path}"   on each command, or by setting SEANCE_HOME:')
        _out(f'  setx SEANCE_HOME "{home}"      (Windows; reopen the terminal afterwards)')
    _out("")
    _out("Next: `seance doctor` checks that Whisper and Gemma are ready.")
    return 0


def cmd_doctor(args, cfg: Config) -> int:
    ok = True
    _out(f"Séance {__version__} · Python {sys.version.split()[0]}")
    _out(f"Config:   {cfg.source or '(defaults; run `seance init`)'}")
    _out(f"Archive:  {cfg.home}")
    try:
        import faster_whisper
        fw = getattr(faster_whisper, "__version__", "?")
        _out(f"✔ faster-whisper {fw} installed (Whisper '{cfg.whisper_model}' downloads on first use)")
        if cfg.whisper_translate_model and cfg.whisper_translate_model != cfg.whisper_model:
            _out(f"  Translations use Whisper '{cfg.whisper_translate_model}'")
        try:
            import av
            major = int(str(av.__version__).split(".")[0])
            if major >= 16:
                ok = False
                _out(f'✘ PyAV {av.__version__} is too new for faster-whisper. Fix:  pip install "av<16"')
            else:
                _out(f"✔ PyAV {av.__version__} (audio decoding)")
        except Exception:  # noqa: BLE001
            pass
    except ImportError:
        ok = False
        _out("✘ faster-whisper is missing. Run:  pip install faster-whisper")
    if cfg.whisper_device != "cpu":
        _out(f"⚠ Whisper device is '{cfg.whisper_device}'. Without NVIDIA's CUDA 12 libraries this fails;"
             ' use device = "cpu" if you see a cublas error.')
    try:
        import sounddevice  # noqa: F401
        _out("✔ sounddevice installed (seance record and --play work)")
    except (ImportError, OSError):
        _out('· sounddevice not installed (optional, for recording/playback):  pip install -e ".[audio]"')

    from .llm import OllamaClient
    llm = OllamaClient(cfg.ollama_url, cfg.model, embed_model=cfg.embed_model, timeout=cfg.timeout,
                       num_ctx=cfg.num_ctx)
    try:
        models = llm.list_models()
        _out(f"✔ Ollama reachable at {cfg.ollama_url}")
    except OllamaError as exc:
        _out(f"✘ {exc}")
        return 1
    if llm.has_model():
        _out(f"✔ Gemma model '{cfg.model}' is pulled")
    else:
        ok = False
        _out(f"✘ Gemma model '{cfg.model}' isn't pulled. Run:  ollama pull {cfg.model}")
        if models:
            _out("  Models you have: " + ", ".join(models))
    if cfg.embed_model and llm.has_model(cfg.embed_model):
        _out(f"✔ Embedding model '{cfg.embed_model}' is pulled (semantic search on)")
    elif cfg.embed_model:
        _out(f"· Embedding model '{cfg.embed_model}' not pulled; search uses keywords only. Optional:"
             f"  ollama pull {cfg.embed_model}")

    if ok and not args.quick:
        from .card import make_card
        from .transcript import parse_text_transcript
        _out("  Asking Gemma to make a test memory card (the first call loads the model)...")
        segs = parse_text_transcript(
            "[00:00] When I was nine we moved to a house with a jackfruit tree in the yard.\n"
            "[00:06] My brother Thomas climbed it every evening and threw the fruit down to me.\n")
        started = time.perf_counter()
        try:
            card = make_card(llm, segs, speaker="Grandpa")
        except OllamaError as exc:
            _out(f"✘ {exc}")
            return 1
        took = time.perf_counter() - started
        kept = len(card.moments)
        _out(f"✔ Gemma replied in {took:.1f}s: “{card.title}”, {kept} verified quote{'s' if kept != 1 else ''}"
             + (f", {card.dropped_quotes} rejected" if card.dropped_quotes else ""))
    _out("All good. 🕯️" if ok else "Fix the ✘ items above, then run `seance doctor` again.")
    return 0 if ok else 1


def _add_paths(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        path = Path(p).expanduser()
        if path.is_dir():
            out += sorted(x for x in path.iterdir() if x.suffix.lower() in AUDIO_EXTENSIONS | {".txt"})
        else:
            out.append(path)
    return out


def cmd_add(args, cfg: Config) -> int:
    cfg.ensure_dirs()
    app = _app(cfg)
    failures = 0
    paths = _add_paths(args.files)
    if not paths:
        _out("Nothing to add.")
        return 1
    for i, path in enumerate(paths):
        if i:
            _out("\n" + "─" * 60 + "\n")
        try:
            result = app.add_file(path, speaker=args.speaker, title=args.title if len(paths) == 1 else None,
                                  recorded=_parse_date(args.date), translate=args.translate, note=args.note or "",
                                  language=args.language)
            _print_add(result, cfg)
        except (OllamaError, RuntimeError, ValueError, FileNotFoundError) as exc:
            failures += 1
            _out(f"✘ {path.name}: {exc}")
    return 1 if failures else 0


def cmd_record(args, cfg: Config) -> int:
    from .audio import record_wav
    cfg.ensure_dirs()
    stamp = datetime.now()
    path = cfg.inbox / f"recording_{stamp:%Y%m%d_%H%M%S}.wav"
    if args.seconds:
        _out(f"🎙️  Recording {args.speaker} for {args.seconds:.0f}s... go ahead.")
    else:
        _out(f"🎙️  Recording {args.speaker}... press Enter to stop.")

    def tick(elapsed: float) -> None:
        sys.stdout.write(f"\r   ● {fmt_ts(elapsed)} ")
        sys.stdout.flush()

    try:
        length = record_wav(path, seconds=args.seconds, on_tick=tick)
    except RuntimeError as exc:
        _out(f"\n✘ {exc}")
        return 1
    _out(f"\r   Saved {fmt_duration(length)} to {path}")
    if length < 1.0:
        _out("✘ That was too short to transcribe.")
        return 1
    app = _app(cfg)
    try:
        result = app.add_file(path, speaker=args.speaker, title=args.title, recorded=stamp,
                              translate=args.translate, note=args.note or "", language=args.language)
    except (OllamaError, RuntimeError, ValueError) as exc:
        _out(f"✘ {exc}")
        _out(f"   The recording is kept at {path}; try again with `seance add \"{path}\" --speaker {args.speaker}`.")
        return 1
    try:
        path.unlink()  # the archive has its own copy in recordings/
    except OSError:
        pass
    _print_add(result, cfg)
    return 0


def _play(cfg: Config, story, start, end) -> None:
    from .audio import play_moment
    if not story.audio:
        _out("   (no audio for this story: it was added from a text transcript)")
        return
    _out(f"   ▶ playing {story.speaker} at {fmt_ts(start)}...")
    try:
        play_moment(cfg.home / story.audio, start, end)
    except RuntimeError as exc:
        _out(f"   ✘ {exc}")


def _ask_once(app, cfg: Config, question: str, args) -> None:
    from .ask import render_answer
    try:
        ans = app.ask(question, speaker=args.speaker, k=args.k)
    except OllamaError as exc:
        _out(f"✘ {exc}")
        return
    _out(render_answer(ans, show_passages=args.passages))
    _out(f"\n   ({len(ans.hits)} passages read · Gemma took {ans.seconds:.1f}s"
         + (f" · {ans.dropped} unverifiable quote{'s' if ans.dropped != 1 else ''} removed" if ans.dropped else "")
         + ")")
    if args.play and ans.citations:
        c = ans.citations[0]
        _play(cfg, c.story, c.start, c.end)


def cmd_ask(args, cfg: Config) -> int:
    _need_archive(cfg)
    app = _app(cfg)
    if not app.archive.stories():
        _out("The archive is empty. Add a story first with `seance record` or `seance add`.")
        return 1
    if args.question:
        _ask_once(app, cfg, " ".join(args.question), args)
        return 0
    _out("🕯️  Ask the archive anything. An empty line ends the séance.")
    while True:
        try:
            q = input("\n? ").strip()
        except (EOFError, KeyboardInterrupt):
            _out("")
            break
        if not q:
            break
        _ask_once(app, cfg, q, args)
    return 0


def cmd_play(args, cfg: Config) -> int:
    _need_archive(cfg)
    app = _app(cfg)
    story = _find(app, args.story)
    if story is None:
        return 1
    if args.moment:
        moments = story.card.moments
        if not 1 <= args.moment <= len(moments):
            _out(f"✘ {story.title} has {len(moments)} moments; pick 1 to {len(moments)}.")
            return 1
        m = moments[args.moment - 1]
        _out(f"   “{m.quote}”")
        _play(cfg, story, m.start, m.end)
        return 0
    start = parse_ts(args.at) if args.at else 0.0
    if start is None:
        _out("✘ Give the time as mm:ss, e.g. 03:12")
        return 1
    _play(cfg, story, start, start + args.seconds)
    return 0


def _find(app, key: str):
    try:
        story = app.archive.find(key)
    except LookupError as exc:
        _out(f"✘ {exc}")
        return None
    if story is None:
        _out(f"✘ No story matches '{key}'. `seance list` shows them all.")
    return story


def cmd_list(args, cfg: Config) -> int:
    _need_archive(cfg)
    app = _app(cfg)
    stories = app.archive.stories()
    if args.speaker:
        stories = [s for s in stories if s.speaker.casefold() == args.speaker.casefold()]
    if not stories:
        _out("No stories yet.")
        return 0
    for s in stories:
        dur = fmt_duration(s.duration) if s.duration else "text"
        _out(f"{s.recorded_date}  {s.speaker:<14.14} {s.title:<44.44} {dur:>10}  {len(s.card.moments)} quotes  {s.id}")
    return 0


def cmd_show(args, cfg: Config) -> int:
    _need_archive(cfg)
    story = _find(_app(cfg), args.story)
    if story is None:
        return 1
    print_story_card(story)
    if args.transcript:
        _out("")
        for seg in story.working:
            ts = fmt_ts(seg.start)
            _out(f"[{ts}] {seg.text}" if ts else seg.text)
    return 0


def cmd_person(args, cfg: Config) -> int:
    _need_archive(cfg)
    app = _app(cfg)
    photo = None
    if args.photo:
        src = Path(args.photo).expanduser()
        if not src.is_file():
            _out(f"✘ No such photo: {src}")
            return 1
        cfg.photos_dir.mkdir(parents=True, exist_ok=True)
        from .archive import slugify
        dest = cfg.photos_dir / f"{slugify(args.name)}{src.suffix.lower()}"
        shutil.copy2(src, dest)
        photo = dest.relative_to(cfg.home).as_posix()
    entry = app.archive.set_person(args.name, relation=args.relation, years=args.years, note=args.note, photo=photo)
    app.refresh()
    _out(f"✔ {app.archive.canonical_speaker(args.name)}: " + ", ".join(f"{k}={v}" for k, v in entry.items()) if entry
         else f"✔ {args.name}")
    return 0


def cmd_people(args, cfg: Config) -> int:
    _need_archive(cfg)
    app = _app(cfg)
    people = app.archive.people()
    rows = app.archive.speakers()
    if not rows:
        _out("No one yet.")
    for name, count in rows:
        info = people.get(name, {})
        extra = " · ".join(x for x in (info.get("relation"), info.get("years")) if x)
        _out(f"{name:<18} {count} {'story' if count == 1 else 'stories'}" + (f"   {extra}" if extra else ""))
    return 0


def cmd_questions(args, cfg: Config) -> int:
    _need_archive(cfg)
    app = _app(cfg)
    stories = app.archive.stories()
    if args.speaker:
        stories = [s for s in stories if s.speaker.casefold() == args.speaker.casefold()]
    any_q = False
    for name in dict.fromkeys(s.speaker for s in stories):
        qs = [(s, q) for s in stories if s.speaker == name for q in s.card.follow_up_questions]
        if not qs:
            continue
        any_q = True
        _out(f"Next time you sit with {name}, ask:")
        for s, q in qs:
            _out(f"  · {q}   ({s.title})")
        _out("")
    if not any_q:
        _out("No follow-up questions yet.")
    return 0


def cmd_ofrenda(args, cfg: Config) -> int:
    _need_archive(cfg)
    from .ofrenda import write_ofrenda
    app = _app(cfg)
    path = write_ofrenda(app.archive, title=args.title, only=args.speaker)
    _out(f"✿  {path}")
    if args.open:
        webbrowser.open(Path(path).resolve().as_uri())
    return 0


def cmd_reindex(args, cfg: Config) -> int:
    _need_archive(cfg)
    app = _app(cfg)
    started = time.perf_counter()
    embedded = app.reindex()
    app.refresh()
    n = len(app.index.chunks)
    _out(f"✔ Indexed {n} passages in {time.perf_counter() - started:.1f}s "
         + ("with EmbeddingGemma + keywords" if embedded else "(keywords only)"))
    return 0


def cmd_remove(args, cfg: Config) -> int:
    _need_archive(cfg)
    app = _app(cfg)
    story = _find(app, args.story)
    if story is None:
        return 1
    trash = app.remove(story)
    _out(f"✔ Moved “{story.title}” to {trash}")
    return 0


def cmd_stats(args, cfg: Config) -> int:
    _need_archive(cfg)
    app = _app(cfg)
    stories = app.archive.stories()
    log = app.archive.read_log()
    adds = [e for e in log if e.get("event") == "add"]
    asks = [e for e in log if e.get("event") == "ask"]
    audio = sum(s.duration for s in stories)
    moments = sum(len(s.card.moments) for s in stories)
    _out("🕯️  Séance archive")
    _out(f"Stories:                 {len(stories)} from {len({s.speaker for s in stories})} "
         f"{'person' if len({s.speaker for s in stories}) == 1 else 'people'}")
    _out(f"Recorded voices:         {fmt_duration(audio)}")
    _out(f"Moments in their words:  {moments}")
    timed = [e for e in adds if e.get("audio_seconds") and e.get("transcribe_seconds")]
    if timed:
        a = sum(e["audio_seconds"] for e in timed)
        t = sum(e["transcribe_seconds"] for e in timed)
        _out(f"Whisper speed:           {a / t:.1f}× real time ({fmt_duration(a)} of audio in {t:.0f}s)")
    if adds:
        g = [e.get("gemma_seconds", 0) for e in adds]
        _out(f"Gemma per memory card:   {sum(g) / len(g):.1f}s on average")
        dropped = sum(e.get("dropped_quotes", 0) for e in adds)
        offered = dropped + sum(e.get("moments", 0) for e in adds)
        _out(f"Quotes rejected:         {dropped} of {offered} Gemma suggested (not found in the recording)")
    if asks:
        g = [e.get("gemma_seconds", 0) for e in asks]
        verified = sum(1 for e in asks if e.get("citations"))
        _out(f"Questions asked:         {len(asks)} ({verified} answered with verified quotes), "
             f"{sum(g) / len(g):.1f}s each on average")
    return 0


# Parser ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="seance", description="Séance: ask your family's stories a question.")
    p.add_argument("--config", help="path to config.toml")
    p.add_argument("--version", action="version", version=f"seance {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="create the archive folder and config")
    s.add_argument("--home", help="where to keep the archive (default ~/Seance)")
    s.add_argument("--force", action="store_true", help="overwrite an existing config.toml")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("doctor", help="check Whisper, Ollama and Gemma")
    s.add_argument("--quick", action="store_true", help="skip the test call to Gemma")
    s.set_defaults(func=cmd_doctor)

    def story_opts(sp):
        sp.add_argument("--speaker", "-s", required=True, help="whose story this is, e.g. Grandma")
        sp.add_argument("--title", "-t", help="a title (otherwise Gemma suggests one)")
        sp.add_argument("--note", help="a note to keep with the story")
        tr = sp.add_mutually_exclusive_group()
        tr.add_argument("--translate", dest="translate", action="store_true", default=None,
                        help="also make an English translation (for recordings in other languages)")
        tr.add_argument("--no-translate", dest="translate", action="store_false")
        sp.add_argument("--language", "-l", help='the language spoken, e.g. ml (Malayalam), hi, ta, ar, en '
                                                 '(default: auto-detect, or [whisper] language in config)')

    s = sub.add_parser("add", help="add recordings or transcripts to the archive")
    s.add_argument("files", nargs="+", help="recordings (.m4a .mp3 .wav .opus .amr .3gp .mp4 ...), "
                                           ".txt transcripts, or a folder of them")
    story_opts(s)
    s.add_argument("--date", help="when it was recorded, YYYY-MM-DD (default: from the file)")
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("record", help="record a story from the microphone, then add it")
    story_opts(s)
    s.add_argument("--seconds", type=float, help="stop after this many seconds (default: press Enter)")
    s.set_defaults(func=cmd_record)

    s = sub.add_parser("ask", help="ask the archive a question (no question = keep asking)")
    s.add_argument("question", nargs="*")
    s.add_argument("--speaker", "-s", help="only search this person's stories")
    s.add_argument("--play", action="store_true", help="play the first quoted moment aloud")
    s.add_argument("--passages", action="store_true", help="also show the passages Gemma read")
    s.add_argument("-k", type=int, help="how many passages Gemma reads (default 6)")
    s.set_defaults(func=cmd_ask)

    s = sub.add_parser("play", help="play a moment from a story")
    s.add_argument("story", help="story id or title")
    s.add_argument("at", nargs="?", help="time to start, mm:ss")
    s.add_argument("--moment", "-m", type=int, help="play quote number N from the story's card")
    s.add_argument("--seconds", type=float, default=20.0, help="how long to play from a time (default 20)")
    s.set_defaults(func=cmd_play)

    s = sub.add_parser("list", help="list the stories")
    s.add_argument("--speaker", "-s")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("show", help="show a story's memory card")
    s.add_argument("story")
    s.add_argument("--transcript", action="store_true", help="print the full transcript too")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("person", help="add details about someone: relation, years, photo")
    s.add_argument("name")
    s.add_argument("--relation", help='e.g. "Dad\'s mother"')
    s.add_argument("--years", help='e.g. "1938–2019"')
    s.add_argument("--photo", help="a photo for the ofrenda")
    s.add_argument("--note", help="a line about them")
    s.set_defaults(func=cmd_person)

    s = sub.add_parser("people", help="list everyone in the archive")
    s.set_defaults(func=cmd_people)

    s = sub.add_parser("questions", help="questions to ask next time")
    s.add_argument("--speaker", "-s")
    s.set_defaults(func=cmd_questions)

    s = sub.add_parser("ofrenda", help="rebuild the ofrenda page")
    s.add_argument("--title", default="Our family's stories")
    s.add_argument("--speaker", "-s", help="make the page for one person only")
    s.add_argument("--open", action="store_true", help="open it in your browser")
    s.set_defaults(func=cmd_ofrenda)

    s = sub.add_parser("reindex", help="rebuild search (e.g. after pulling embeddinggemma)")
    s.set_defaults(func=cmd_reindex)

    s = sub.add_parser("remove", help="move a story to the archive's trash folder")
    s.add_argument("story")
    s.set_defaults(func=cmd_remove)

    s = sub.add_parser("stats", help="what's in the archive, and how fast it ran")
    s.set_defaults(func=cmd_stats)
    return p


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdout()
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
    except FileNotFoundError as exc:
        _out(f"✘ {exc}")
        return 1
    try:
        return int(args.func(args, cfg) or 0)
    except OllamaError as exc:
        _out(f"✘ {exc}")
        return 1
    except KeyboardInterrupt:
        _out("\nStopped.")
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
