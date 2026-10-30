"""The ofrenda: a single offline HTML page that honours the people in the archive.

In the Día de los Muertos tradition an ofrenda holds photos, favourite things
and memories of the people being remembered. This one holds their own words:
every quote is verbatim from a recording, and the ▶ button plays that exact
moment in their voice. The page needs no internet and no server; open the file.
"""

from __future__ import annotations

from datetime import datetime
from html import escape

from .archive import Archive, Story, atomic_write_text
from .card import year_of
from .render import fmt_duration
from .transcript import fmt_ts

CSS = r"""
:root{
  --bg:#1b1220; --bg2:#24182b; --card:#2c1f33; --ink:#f6ece0; --muted:#c9b8a8;
  --marigold:#f5a524; --marigold2:#ff8a00; --magenta:#e0428f; --teal:#2bb3a3; --line:#4a3550;
  --quote:#fff7ea; --shadow:0 10px 30px rgba(0,0,0,.35);
}
@media (prefers-color-scheme: light){
  :root{ --bg:#fbf4ea; --bg2:#f6e9d8; --card:#fffaf3; --ink:#2b1d14; --muted:#6f5a4b;
         --marigold:#d98100; --marigold2:#c46a00; --magenta:#b42a6f; --teal:#13867a; --line:#e6d3bd;
         --quote:#2b1d14; --shadow:0 8px 24px rgba(80,40,0,.10); }
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{background:radial-gradient(1200px 600px at 50% -10%, var(--bg2), var(--bg) 70%) fixed;
  color:var(--ink); font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--marigold)}
.wrap{max-width:1040px;margin:0 auto;padding:0 16px}
.picado{display:block;width:100%;height:72px}
header{text-align:center;padding:8px 0 24px}
header h1{font-family:Georgia,"Times New Roman",serif;font-weight:700;font-size:clamp(2rem,5vw,3.2rem);
  margin:.2em 0 .1em;letter-spacing:.5px}
header h1 span{color:var(--marigold)}
header p{color:var(--muted);margin:.2em 0}
.chips{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin:18px 0 6px}
.chip{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;
  padding:6px 14px;text-decoration:none;font-size:.95rem}
.chip:hover{border-color:var(--marigold)}
.search{display:flex;justify-content:center;margin:14px 0 0}
.search input{width:min(520px,100%);padding:10px 14px;border-radius:12px;border:1px solid var(--line);
  background:var(--card);color:var(--ink);font:inherit}
section.person{margin:34px 0 10px;padding:24px;border-radius:22px;background:linear-gradient(180deg,var(--card),transparent 140%);
  border:1px solid var(--line);box-shadow:var(--shadow);position:relative}
.altar{display:grid;grid-template-columns:180px 1fr;gap:24px;align-items:center}
@media (max-width:640px){.altar{grid-template-columns:1fr;text-align:center}}
.frame{width:180px;height:220px;margin:0 auto;border-radius:14px;padding:8px;
  background:repeating-linear-gradient(45deg,var(--marigold) 0 8px,var(--marigold2) 8px 16px);
  box-shadow:0 0 0 3px var(--magenta), var(--shadow)}
.frame div{width:100%;height:100%;border-radius:9px;background:var(--bg2) center/cover no-repeat;
  display:flex;align-items:center;justify-content:center;font-family:Georgia,serif;font-size:3.4rem;color:var(--marigold)}
.candles{display:flex;gap:18px;justify-content:center;margin-top:12px}
.candle{width:12px;height:30px;background:#f3e6c8;border-radius:3px;position:relative}
.candle::before{content:"";position:absolute;left:50%;top:-14px;width:10px;height:14px;transform:translateX(-50%);
  background:radial-gradient(circle at 50% 70%,#fff6a8,#ffb400 55%,rgba(255,120,0,0) 70%);border-radius:50% 50% 45% 45%;
  animation:flick 1.6s infinite ease-in-out}
.candle:nth-child(2)::before{animation-delay:.4s}.candle:nth-child(3)::before{animation-delay:.9s}
@keyframes flick{0%,100%{transform:translateX(-50%) scale(1)}50%{transform:translateX(-48%) scale(1.12,0.92)}}
.who h2{font-family:Georgia,serif;font-size:2rem;margin:0}
.who .rel{color:var(--marigold);font-weight:600}
.who .note{color:var(--muted);margin-top:6px}
.stats{color:var(--muted);font-size:.92rem;margin-top:6px}
h3{font-family:Georgia,serif;font-size:1.25rem;margin:28px 0 12px;color:var(--marigold)}
.quotes{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}
.q{background:var(--bg2);border:1px solid var(--line);border-left:4px solid var(--magenta);border-radius:14px;padding:16px 16px 12px}
.q blockquote{margin:0;font-family:Georgia,serif;font-size:1.08rem;line-height:1.55;color:var(--quote)}
.q .orig{color:var(--muted);font-size:.9rem;margin-top:8px;font-style:italic}
.q .meta{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:10px;color:var(--muted);font-size:.86rem}
.q .heading{font-weight:600;color:var(--ink)}
button.play{border:0;border-radius:999px;background:var(--marigold);color:#2b1400;font-weight:700;
  padding:6px 12px;cursor:pointer;white-space:nowrap;font:600 .85rem system-ui,sans-serif}
button.play.on{background:var(--magenta);color:#fff}
.stories{display:grid;gap:12px}
.story{border:1px solid var(--line);border-radius:14px;padding:14px 16px;background:var(--bg2)}
.story h4{margin:0 0 4px;font-size:1.05rem}
.story .sm{color:var(--muted);font-size:.88rem}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.tag{font-size:.8rem;padding:2px 9px;border-radius:999px;border:1px solid var(--line);color:var(--muted)}
.tag.place{border-color:var(--teal);color:var(--teal)}
ul.asks{margin:0;padding-left:20px;color:var(--ink)}
ul.asks li{margin:4px 0}
.timeline{border-left:3px solid var(--marigold);margin:0 0 0 8px;padding:0 0 0 18px}
.timeline .ev{position:relative;margin:0 0 14px}
.timeline .ev::before{content:"";position:absolute;left:-26px;top:7px;width:13px;height:13px;border-radius:50%;
  background:var(--magenta);box-shadow:0 0 0 3px var(--bg)}
.timeline .yr{font-weight:700;color:var(--marigold);margin-right:8px}
.timeline .by{color:var(--muted);font-size:.88rem}
footer{color:var(--muted);text-align:center;font-size:.9rem;padding:40px 0 60px}
.petal{position:fixed;top:-20px;width:12px;height:12px;border-radius:60% 0 60% 0;background:var(--marigold);
  opacity:.55;pointer-events:none;animation:fall linear infinite}
@keyframes fall{to{transform:translateY(110vh) rotate(540deg)}}
@media (prefers-reduced-motion: reduce){.petal{display:none}.candle::before{animation:none}}
.hidden{display:none!important}
.empty{color:var(--muted);font-style:italic}
"""

JS = r"""
(function(){
  const audio = new Audio(); audio.preload = "none";
  let current = null, stopAt = null;
  function reset(){ if(current){ current.classList.remove('on'); current.textContent = current.dataset.label; } current = null; stopAt = null; }
  audio.addEventListener('timeupdate', ()=>{ if(stopAt!==null && audio.currentTime >= stopAt){ audio.pause(); reset(); } });
  audio.addEventListener('ended', reset);
  audio.addEventListener('error', ()=>{ if(current){ current.textContent = 'audio missing'; current.disabled = true; } current = null; });
  document.querySelectorAll('button.play').forEach(btn=>{
    btn.dataset.label = btn.textContent;
    btn.addEventListener('click', ()=>{
      if(current === btn){ audio.pause(); reset(); return; }
      reset();
      const src = btn.dataset.src, start = parseFloat(btn.dataset.start||'0'), end = parseFloat(btn.dataset.end||'NaN');
      const go = ()=>{ audio.currentTime = Math.max(0, start - 0.3); audio.play().catch(()=>{}); };
      if(!audio.src.endsWith(encodeURI(src))){ audio.src = src; audio.addEventListener('loadedmetadata', go, {once:true}); audio.load(); }
      else { go(); }
      stopAt = isNaN(end) ? start + 20 : end + 0.4;
      current = btn; btn.classList.add('on'); btn.textContent = '■ stop';
    });
  });
  const box = document.getElementById('filter');
  if(box){ box.addEventListener('input', ()=>{
    const t = box.value.trim().toLowerCase();
    document.querySelectorAll('[data-search]').forEach(el=>{
      el.classList.toggle('hidden', t && !el.dataset.search.includes(t));
    });
  }); }
  if(!window.matchMedia('(prefers-reduced-motion: reduce)').matches){
    for(let i=0;i<14;i++){ const p=document.createElement('div'); p.className='petal';
      p.style.left=(Math.random()*100)+'vw'; p.style.animationDuration=(9+Math.random()*10)+'s';
      p.style.animationDelay=(-Math.random()*15)+'s'; p.style.transform='scale('+(0.6+Math.random()*0.8)+')';
      document.body.appendChild(p); }
  }
})();
"""


def _picado() -> str:
    """A string of papel picado flags as inline SVG, with real cut-out holes (even-odd fill)."""
    colors = ["#e0428f", "#f5a524", "#2bb3a3", "#8e5cf7", "#ff6b3d", "#f5d000"]
    w, n = 80, 30
    flags = []
    for i in range(n):
        x = i * w
        cx = x + w / 2
        outline = (f"M{x + 4},8 L{x + w - 4},8 L{x + w - 4},60 L{cx + 12},68 L{cx},60 "
                   f"L{cx - 12},68 L{x + 4},60 Z")
        # cut-outs: a diamond flower, four petals around it, and a row of small holes
        diamond = f"M{cx},18 L{cx + 9},30 L{cx},42 L{cx - 9},30 Z"
        petals = "".join(
            f"M{px - 3},{py} a3,3 0 1,0 6,0 a3,3 0 1,0 -6,0 Z"
            for px, py in ((cx - 17, 22), (cx + 17, 22), (cx - 17, 38), (cx + 17, 38))
        )
        holes = "".join(f"M{hx - 2},52 a2,2 0 1,0 4,0 a2,2 0 1,0 -4,0 Z" for hx in (cx - 20, cx - 10, cx, cx + 10, cx + 20))
        flags.append(f'<path fill-rule="evenodd" fill="{colors[i % len(colors)]}" opacity=".92" '
                     f'd="{outline} {diamond} {petals} {holes}"/>')
    return (f'<svg class="picado" viewBox="0 0 {w * n} 72" preserveAspectRatio="xMidYMin slice" aria-hidden="true">'
            f'<path d="M0,8 L{w * n},8" stroke="var(--muted)" stroke-width="2"/>'
            + "".join(flags) + "</svg>")


def _anchor(name: str) -> str:
    return "p-" + "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-")


def _quote_card(story: Story, m) -> str:
    play = ""
    if story.audio and m.start is not None:
        play = (f'<button class="play" data-src="{escape(story.audio)}" data-start="{m.start}" '
                f'data-end="{m.end if m.end is not None else ""}">▶ {fmt_ts(m.start)}</button>')
    orig = f'<div class="orig">{escape(m.original)}</div>' if m.original else ""
    search = escape(f"{m.quote} {m.heading} {story.title} {story.speaker}".lower())
    return (f'<div class="q" data-search="{search}"><blockquote>“{escape(m.quote)}”</blockquote>{orig}'
            f'<div class="meta"><span><span class="heading">{escape(m.heading)}</span> · {escape(story.title)}</span>'
            f"{play}</div></div>")


def build_ofrenda(archive: Archive, *, title: str = "Our family's stories", only: str | None = None,
                  now: datetime | None = None) -> str:
    now = now or datetime.now()
    stories = archive.stories()
    people = archive.people()
    names = [n for n, _ in archive.speakers()]
    if only:
        names = [n for n in names if n.casefold() == only.casefold()]
        stories = [s for s in stories if s.speaker.casefold() == only.casefold()]
    total = sum(s.duration for s in stories)
    moments_count = sum(len(s.card.moments) for s in stories)

    parts: list[str] = []
    parts.append(_picado())
    parts.append('<div class="wrap"><header>')
    parts.append(f"<h1><span>✿</span> {escape(title)} <span>✿</span></h1>")
    sub = f"{len(stories)} {'recording' if len(stories) == 1 else 'recordings'}"
    if total:
        sub += f" · {fmt_duration(total)} of their voices"
    sub += f" · {moments_count} moments in their own words"
    parts.append(f"<p>{escape(sub)}</p>")
    if len(names) > 1:
        parts.append('<nav class="chips">' + "".join(
            f'<a class="chip" href="#{_anchor(n)}">{escape(n)}</a>' for n in names) + "</nav>")
    if moments_count:
        parts.append('<div class="search"><input id="filter" type="search" '
                     'placeholder="Find a word they said: mango, ship, wedding…" aria-label="Filter quotes"></div>')
    parts.append("</header>")

    if not stories and not names:
        parts.append('<p class="empty" style="text-align:center">No stories yet. '
                     "Record one with <code>seance record --speaker NAME</code>.</p>")

    for name in names:
        info = people.get(name, {})
        mine = [s for s in stories if s.speaker == name]
        photo = info.get("photo")
        initial = escape(name[:1].upper())
        style = f' style="background-image:url(&quot;{escape(photo)}&quot;)"' if photo else ""
        portrait = f'<div{style}>{"" if photo else initial}</div>'
        rel = " · ".join(x for x in (info.get("relation"), info.get("years")) if x)
        dur = sum(s.duration for s in mine)
        stats = f"{len(mine)} {'recording' if len(mine) == 1 else 'recordings'}" + (f" · {fmt_duration(dur)}" if dur else "")
        parts.append(f'<section class="person" id="{_anchor(name)}"><div class="altar">'
                     f'<div><div class="frame">{portrait}</div>'
                     '<div class="candles"><span class="candle"></span><span class="candle"></span><span class="candle"></span></div></div>'
                     f'<div class="who"><h2>{escape(name)}</h2>'
                     + (f'<div class="rel">{escape(rel)}</div>' if rel else "")
                     + (f'<div class="note">{escape(info["note"])}</div>' if info.get("note") else "")
                     + f'<div class="stats">{escape(stats)}</div></div></div>')
        moments = [(s, m) for s in mine for m in s.card.moments]
        if moments:
            parts.append("<h3>In their words</h3><div class=\"quotes\">")
            parts += [_quote_card(s, m) for s, m in moments]
            parts.append("</div>")
        if mine:
            parts.append("<h3>Stories</h3><div class=\"stories\">")
            for s in mine:
                tags = "".join(f'<span class="tag place">{escape(p)}</span>' for p in s.card.places[:6])
                tags += "".join(f'<span class="tag">{escape(t)}</span>' for t in s.card.themes[:4])
                meta = f"Recorded {s.recorded_date}" + (f" · {fmt_duration(s.duration)}" if s.duration else "")
                search = escape(f"{s.title} {s.card.summary} {' '.join(s.card.places)}".lower())
                parts.append(f'<div class="story" data-search="{search}"><h4><a href="stories/{escape(s.id)}.md">'
                             f'{escape(s.title)}</a></h4><div class="sm">{escape(meta)}</div>'
                             f"<div>{escape(s.card.summary)}</div><div class=\"tags\">{tags}</div></div>")
            parts.append("</div>")
        asks = [q for s in mine for q in s.card.follow_up_questions][:6]
        if asks:
            parts.append(f"<h3>Still to ask {escape(name)}</h3><ul class=\"asks\">"
                         + "".join(f"<li>{escape(q)}</li>" for q in asks) + "</ul>")
        parts.append("</section>")

    events = []
    for s in stories:
        for y in s.card.years:
            yr = year_of(y["when"])
            if yr is not None:
                events.append((yr, y, s))
    if events:
        parts.append('<section class="person"><h3 style="margin-top:0">Through the years</h3><div class="timeline">')
        for yr, y, s in sorted(events, key=lambda e: e[0]):
            parts.append(f'<div class="ev" data-search="{escape((y["when"] + " " + y["what"]).lower())}">'
                         f'<span class="yr">{escape(y["when"])}</span>{escape(y["what"])} '
                         f'<span class="by">({escape(s.speaker)}, {escape(s.title)})</span></div>')
        parts.append("</div></section>")

    parts.append("<footer>Made with Séance · speech by Whisper and memories by Gemma, both running on this "
                 f"computer · every quote above is word for word from a recording · {now:%d %b %Y}</footer></div>")

    body = "\n".join(parts)
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>Ofrenda · {escape(title)}</title><style>{CSS}</style></head>"
        f"<body>{body}<script>{JS}</script></body></html>\n"
    )


def write_ofrenda(archive: Archive, **kwargs) -> str:
    path = archive.home / "ofrenda.html"
    atomic_write_text(path, build_ofrenda(archive, **kwargs))
    return str(path)

