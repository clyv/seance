# Sample transcripts

Two short, **fictional** family stories in the timestamped format Séance writes, so you can
try the whole flow before recording anyone:

```bash
seance add samples/grandma_the_house_in_kerala.txt --speaker Grandma
seance add samples/grandpa_coming_to_dubai.txt --speaker Grandpa
seance ask "What was the flood like?"
seance ask "How did Grandpa talk to Grandma when he was in Dubai?"
seance questions
seance ofrenda --open
```

Text stories have no audio, so they have no ▶ buttons. Record a real one with
`seance record --speaker NAME` to hear the playback.

To start again with an empty archive, delete the `~/Seance` folder and run `seance init`.
