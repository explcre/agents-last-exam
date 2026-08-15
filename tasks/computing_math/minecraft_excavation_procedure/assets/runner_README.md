# Local runner

`episode.js` builds one world, runs a bot against it, and writes the arena grid
before and after.

```
node episode.js <seed> <port> <path-to-bot.js> <out.json>
```

It starts a `flying-squid` server on `<port>`, lays out the arena from `<seed>`,
writes `arena.json` next to `<out.json>`, loads your module and calls
`run(arena)`, then records the result. A bot that throws or exceeds its time
budget still produces an output file, with the error recorded in `err`.

Pick a different port per run; a port left in TIME_WAIT will fail to bind.

The seeds used for grading are not the seeds in `examples.json`.
