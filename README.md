# civ5-ai

A local LLM plays *Civilization V*. The agent reads the game through the
FireTuner debug socket the game opens on `localhost:4318`, describes the
situation to a model running in [Ollama](https://ollama.com) (default
`qwen2.5:14b`), and carries out the model's tool calls in the game.

The model chooses its own strategy. The prompt gives it only the game's rules
and how the tools work, plus any guidelines you add.

## Requirements

- Civilization V with Brave New World (the agent uses its Lua API)
- Python 3.8+ (standard library only)
- Ollama running locally, with a model that supports tool calling:
  `ollama pull qwen2.5:14b`

## Setup

1. In `Documents\My Games\Sid Meier's Civilization 5\config.ini`, set

   ```ini
   EnableTuner = 1
   LoggingEnabled = 1
   ```

   `LoggingEnabled` is required: without it the game never sends Lua output
   back over the socket.
2. Start the game and load a save or start a new game.
3. In the game's options, turn **off** *Auto End Turn*.
4. Close FireTuner if it is open. The game accepts only one tuner connection.

## Usage

```
py agent.py                      # play until stopped
py agent.py --turns 20           # play 20 turns
py agent.py --say "Go for a science victory and expand to 4 cities first."
py agent.py --model llama3.1:8b  # any Ollama model with tool support
```

While it plays, press **Ctrl+C** to pause after the current turn. You can then
type a message for the model (it's shown to the model on the next turn), press
Enter to continue, or type `q` to quit.

The model keeps its strategy in `plan.txt`, which carries over between runs.
Delete it when you start a new game. Every turn's state, tool calls and
results are logged to `logs/game-<time>.jsonl`.

## How it works

```
 Civ V  <-- FireTuner socket -->  tuner.py  <-- state.py / actions.py -->  agent.py  <-- HTTP -->  Ollama
(Lua API)                       (framing, run Lua)  (lua/*.lua in game)   (turn loop)            (qwen2.5)
```

Each turn the agent:

1. closes leftover informational popups (`popups.py`)
2. reads the game state with `lua/state.lua` and turns it into a compact text
   summary, ending with a **TO DO THIS TURN** checklist (`state.py`)
3. sends that summary to the model along with the tool list (`tools.py`) and the
   rules (`prompt.py`)
4. runs each tool call through `lua/actions.lua`. Every action checks that the move
   is legal and returns `ok: ...` or `error: ...`, which goes back to the model.
5. repeats until the model calls `end_turn`. After 15 actions, simple default
   choices finish the turn instead.
6. waits for the AI players, then starts the next turn

The agent handles research, production, policies, pantheons and religion,
ideology, promotions, combat, purchases with gold or faith, trade routes,
spies, the World Congress, archaeology, great person choices and AI diplomacy
screens (`diplomacy.py`). If the game is blocked on anything else, the agent
pauses and asks you to handle it in the game window.

## Project layout

```
agent.py              entry point (py agent.py)
civ5ai/
  cli.py              command line, Ctrl+C pause
  agent.py            turn loop, guards, fallbacks, logging
  prompt.py           system prompt: rules and guidelines, no strategy
  tools.py            tool definitions sent to the model
  tuner.py            FireTuner socket client
  state.py            game state -> dict -> text summary
  actions.py          Python wrappers for the in-game actions
  popups.py           closes popups the game leaves on screen
  diplomacy.py        AI leader dialogs and trade offers
  lua/state.lua       state snapshot, run inside the game
  lua/actions.lua     actions, installed in the game as _AI
scripts/probe.py      low-level protocol probe (diagnostics)
tests/                offline tests (no game needed)
```

## Adding an action

1. Add `function _AI.my_action(...)` to `civ5ai/lua/actions.lua`. Check that the
   action is legal and return `"ok: ..."` or `"error: ..."`.
2. Add a matching method to `Actions` in `civ5ai/actions.py`.
3. Add a `tool(...)` entry in `civ5ai/tools.py`.
4. If the model needs extra information to use it, add a record to
   `lua/state.lua`, parse it in `state.parse` and show it in `state.summarize`.

`tests/test_tools.py` checks that every tool has both a Lua function and a
Python method.

## Tests

```
py -m unittest discover -s tests -t .
```

## Notes on the game's tuner interface

These quirks were found the hard way. The workarounds live in `tuner.py` and the Lua files.

- Messages are `uint32 length, uint32 listener id, NUL-terminated text`.
  Commands are `CMD:<lua state id>:<code>`, and output comes back as `O` frames.
- Commands over about 2 KB are rejected with an empty `ERR:`. Long code is sent in
  pieces and compiled in the game with `loadstring`, and errors are caught with
  `pcall` so their messages stay short.
- The game serves one client and doesn't notice a normal socket close, so the
  client closes with a reset instead.
- The game API (`Game`, `Players`, `Map`) lives in the `InGame` state, not
  `Main State`. Each popup has its own Lua state.
- `Unit:GeneratePath` isn't implemented ("NYI"), `GetUnitByID` ignores part
  of the id, and the end-turn blocker lags one UI update behind.
- The normal end-turn command is silently ignored while a popup is open, so the
  agent checks the blockers itself and force-ends the turn.

## Status

Tested in a live game: connection, state reading, founding cities, moving units,
research, production, automation, ending turns, closing popups.

Written against the game's own UI scripts but not yet tested in play: religion,
combat, promotions, purchases, trade routes, espionage, World Congress,
archaeology and the diplomacy screens. Please report problems along with the
terminal output for that turn.
