"""Client for the Civ V FireTuner protocol (localhost:4318).

Wire format (worked out with scripts/probe.py and by decompiling FireTuner2.exe):
  frame   = uint32 payload_length, uint32 listener_id, payload
  payload = ASCII text, NUL-terminated; replies may hold several
            NUL-separated fields.
Requests:
  "LSQ:"                -> reply fields alternate: state_id, state_name
  "CMD:<state_id>:<lua>" -> runs Lua; print() output arrives as frames
                           whose first field is "O" (needs LoggingEnabled = 1
                           in config.ini).
The game echoes the listener id back on replies to that request.

Errors come back as a frame whose first field starts with "ERR:".
Commands over ~2048 bytes fail with an empty "ERR:"; run() splits them.

The game serves one tuner connection at a time and does not notice a
graceful (FIN) close, so it stays stuck on a dead client. close() therefore
resets the connection (RST), which the game does notice. Close FireTuner first.
"""
import socket
import struct
import time
import uuid

HOST, PORT = "127.0.0.1", 4318
CHUNK = 1500  # bytes of Lua per command; the game's limit is ~2048 per frame


class TunerError(Exception):
    pass


class Tuner:
    def __init__(self, host=HOST, port=PORT, timeout=5, attempts=4):
        # Right after a previous client disconnects, the game may reset the
        # new connection, so retry until LSQ succeeds.
        for attempt in range(attempts):
            self.sock = socket.create_connection((host, port), timeout=timeout)
            self.buf = b""
            self.states = {}
            try:
                self.list_states()
                return
            except (OSError, TunerError):
                self.sock.close()
                if attempt == attempts - 1:
                    raise
                time.sleep(0.5)

    def close(self):
        # linger on, timeout 0 -> close() sends RST instead of FIN
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        self.sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- framing -----------------------------------------------------------

    def send(self, text, listener=0):
        payload = text.encode("utf-8") + b"\0"
        self.sock.sendall(struct.pack("<II", len(payload), listener) + payload)

    def recv_frame(self, timeout):
        """Return (listener, [fields]) or None if nothing arrives in time."""
        deadline = time.time() + timeout
        while True:
            if len(self.buf) >= 8:
                n, listener = struct.unpack_from("<II", self.buf)
                if len(self.buf) >= 8 + n:
                    payload = self.buf[8:8 + n]
                    self.buf = self.buf[8 + n:]
                    fields = payload.rstrip(b"\0").split(b"\0")
                    return listener, [f.decode("utf-8", "replace") for f in fields]
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            self.sock.settimeout(remaining)
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                return None
            if not chunk:
                raise TunerError("game closed the connection")
            self.buf += chunk

    # -- requests ----------------------------------------------------------

    def list_states(self, timeout=3):
        """Return {name: id} for the game's Lua states."""
        self.send("LSQ:", listener=1)
        frame = self.recv_frame(timeout)
        if frame is None:
            raise TunerError("no reply to LSQ")
        fields = frame[1]
        if fields and fields[0] == "L":
            fields = fields[1:]
        # several states can share a name (e.g. SaveMenu), so keep the full list too
        self.state_list = [(int(fields[i]), fields[i + 1]) for i in range(0, len(fields) - 1, 2)]
        self.states = {name: sid for sid, name in self.state_list}
        return self.states

    def state_id(self, state):
        if isinstance(state, int):
            return state
        if state not in self.states:
            self.list_states()  # the game adds and removes states (menus vs. a loaded game)
        if state not in self.states:
            raise TunerError(f"the game has no '{state}' Lua state right now - is a game loaded?")
        return self.states[state]

    def run(self, lua, state="InGame", timeout=5):
        """Run Lua in the game and return the lines it print()ed.

        The game rejects commands over ~2048 bytes (with a bare "ERR:"), and
        its own error messages echo the whole command, so they get dropped
        too. So the code is sent as a string, compiled with loadstring and
        run under pcall, and we print short errors ourselves. Long code is
        sent in pieces into a global buffer first.
        """
        level = "=" * next(n for n in range(1, 10) if f"]{'=' * n}]" not in lua)
        # long brackets drop a leading newline, so give each piece one to drop
        def quote(s):
            return f"[{level}[\n{s}]{level}]"
        if len(lua.encode("utf-8")) <= CHUNK:
            src = quote(lua)
        else:
            self._exec("_AI_BUF = {}", state)
            for i in range(0, len(lua), CHUNK):
                self._exec(f"_AI_BUF[#_AI_BUF + 1] = {quote(lua[i:i + CHUNK])}", state)
            src = "table.concat(_AI_BUF)"
        lines = self._exec(
            f"_AI_SRC = {src}; _AI_BUF = nil "
            "local f, e = loadstring(_AI_SRC, 'ai') "
            "if f then local ok, e2 = pcall(f) e = (not ok) and tostring(e2) or nil end "
            "if e then print('__err__' .. e:gsub('\\n', ' | ')) end", state, timeout)
        if lines and lines[-1].startswith("__err__"):
            raise TunerError(lines[-1][len("__err__"):])
        return lines

    def _other_state_line(self, line, state):
        head, sep, _ = line.partition(": ")
        return bool(sep) and head != state and head in self.states

    def _exec(self, lua, state="InGame", timeout=5):
        """Send one CMD and collect its output.

        A unique marker is printed after the code so we know when its output
        is complete. If the code errors, the marker never prints and the
        error text (if the game sends it) is raised instead.
        """
        marker = f"__done_{uuid.uuid4().hex[:8]}__"
        sid = self.state_id(state)
        # output from most states arrives as "<state name>: text"
        name = state if isinstance(state, str) else dict(self.state_list).get(sid)
        prefix = f"{name}: " if name else None
        state = name
        self.send(f"CMD:{sid}:{lua}\nprint('{marker}')", listener=2)
        lines = []
        deadline = time.time() + timeout
        while True:
            frame = self.recv_frame(max(0, deadline - time.time()))
            if frame is None:
                raise TunerError(f"no completion marker; output so far: {lines}")
            _, fields = frame
            if fields[0].startswith("ERR:"):
                # the error text may be split over the next few frames
                parts = ["\n".join(fields)[4:]]
                while (more := self.recv_frame(0.3)) is not None:
                    parts.append("\n".join(f for f in more[1] if f != "O"))
                raise TunerError("\n".join(p for p in parts if p))
            text ="\n".join(fields[1:]) if fields[0] == "O" else "\n".join(fields)
            for line in text.splitlines():
                # print() output may be prefixed with the state name, e.g. "Main State: hi"
                body = line[len(prefix):] if prefix and line.startswith(prefix) else line
                # other Lua states' log output (e.g. "TurnProcessing: ...") arrives too
                if self._other_state_line(body, state):
                    continue
                if body.strip() == marker:
                    return lines
                if body.startswith("__done_"):
                    continue  # late marker from an earlier command that timed out
                lines.append(body)


if __name__ == "__main__":
    with Tuner() as t:
        states = t.list_states()
        print(f"{len(states)} Lua states; Main State = {states.get('Main State')}")
        # Find which states expose the game API (Main State does not).
        for name in ["InGame", "WorldView", "TopPanel", "CityView"]:
            if name in states:
                print(f"  {name}:", t.run("print(type(Game), type(Players), type(Map))", state=name))
