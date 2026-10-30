# Submission checklist

**Deadline: Saturday 31 October, 11:59 PM PDT = Sunday 1 November, 10:59 AM Dubai time.**

## Rules that matter

- [ ] Create a **new** public repo, `clyv/seance`, during the challenge window (26 to 31 Oct).
- [ ] Any commits after the deadline are listed in the README, or the entry can be disqualified.
- [ ] The post uses the Week 4 template and the `devchallenge` + `hf26challenge` tags.
- [ ] Prior work is credited. The README says `llm.py` and `audio.py` are adapted from TalkDown.
- [ ] The post is in English.

## Build and test on your machine (same as TalkDown)

- [ ] `ollama pull gemma4:e4b` (you already have it) and `ollama pull embeddinggemma`
- [ ] New venv in the project folder, then `pip install -e ".[audio,dev]"`, then `pytest`
- [ ] `seance init`, then `seance doctor` until everything shows ✔
- [ ] Add both sample transcripts and ask a couple of questions
- [ ] Get at least one real recording of a family member (ask permission first). It doesn't have
      to be in person: a WhatsApp voice note or a recorded call works. Ask them to tell one
      story, e.g. "Tell me about the house you grew up in", for 2 to 5 minutes.
- [ ] If it's in Malayalam, add it with `--language ml --translate` and note honestly how the
      transcript and translation did. If it's poor, try the Malayalam-tuned model in the README
      and compare; that comparison is a strong paragraph for "Why open innovation matters".
- [ ] Turn Wi-Fi off, add a recording and ask a question, so the offline claim is checked
- [ ] Run `seance stats` and copy the numbers for the post

## Demo video (about 90 seconds)

1. Open on the ofrenda page (`seance ofrenda --open`) for a few seconds. It's the visual hook.
2. Terminal: `seance add "PTT-....opus" --speaker NAME` with a voice note from a family member
   (or `seance record` if you're together). Show the memory card appear.
3. `seance ask "..." --play`: ask something they talked about, show the quoted answer, and let
   the clip of their voice play. This is the moment that sets the project apart.
4. Back to the ofrenda, refresh, click a ▶ button on one of the new quotes.
5. Optional: `seance questions` to show what to ask next time.

Cut the waiting while Gemma thinks, or caption it "Gemma thinking locally (sped up)".

## Write-up

- [ ] Fill every ⟨placeholder⟩ in `docs/DEVTO_POST.md` with real numbers and observations
- [ ] Write "The Spirit of It" from a real moment, or delete the section
- [ ] Replace the demo placeholder and the illustrative example output in `README.md`
- [ ] Paste into dev.to: title and tags in their boxes, body in the editor, preview, publish
- [ ] Check the GitHub and YouTube embeds render
