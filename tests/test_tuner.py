"""FireTuner framing over a local socket pair, without the game."""
import socket
import struct
import unittest

from civ5ai.actions import _lua_arg
from civ5ai.tuner import Tuner


def frame(fields, listener=2):
    payload = b"\0".join(f.encode() for f in fields) + b"\0"
    return struct.pack("<II", len(payload), listener) + payload


class FramingTest(unittest.TestCase):
    def setUp(self):
        self.ours, self.game = socket.socketpair()
        self.t = Tuner.__new__(Tuner)  # skip connecting to the game
        self.t.sock, self.t.buf, self.t.states, self.t.state_list = self.ours, b"", {}, []

    def tearDown(self):
        self.ours.close()
        self.game.close()

    def test_send(self):
        self.t.send("LSQ:", listener=1)
        self.assertEqual(self.game.recv(100), struct.pack("<II", 5, 1) + b"LSQ:\0")

    def test_recv_split_and_joined_frames(self):
        data = frame(["O", "hello"]) + frame(["O", "world"])
        self.game.sendall(data[:5])
        self.game.sendall(data[5:])
        self.assertEqual(self.t.recv_frame(1), (2, ["O", "hello"]))
        self.assertEqual(self.t.recv_frame(1), (2, ["O", "world"]))
        self.assertIsNone(self.t.recv_frame(0.1))

    def test_list_states(self):
        self.game.sendall(frame(["0", "Main State", "172", "InGame", "91", "SaveMenu", "154", "SaveMenu"], 1))
        states = self.t.list_states()
        self.assertEqual(states["InGame"], 172)
        self.assertEqual(len(self.t.state_list), 4)  # duplicate names are kept in the list


class LuaArgTest(unittest.TestCase):
    def test_values(self):
        self.assertEqual(_lua_arg(True), "true")
        self.assertEqual(_lua_arg(5), "5")
        self.assertEqual(_lua_arg('say "hi"\\'), '"say \\"hi\\"\\\\"')
        self.assertEqual(_lua_arg("a\nb"), '"a\\010b"')
        # an injection attempt stays a plain string
        self.assertEqual(_lua_arg('x") os.exit() --'), '"x\\") os.exit() --"')


if __name__ == "__main__":
    unittest.main()
