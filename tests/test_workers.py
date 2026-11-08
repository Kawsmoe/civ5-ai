"""Worker jobs: the repeat-the-same-tile loops seen in the logs, and what stops them."""
import unittest

from civ5ai.state import parse, summarize
from civ5ai.workers import WorkerJobs
from tests.test_state import SNAPSHOT, T


def worker(uid, x, y, activity="0", moves="2"):
    return [T.join(["U", str(uid), "UNIT_WORKER", str(x), str(y), moves, "2", "100", activity, "false", "false"]),
            T.join(["UX", str(uid), "0", "0", "0", "10", "false"])]


def resource(x, y, improved=False, imp="", ours=True, building=""):
    # CR: city id, resource, class, x, y, improved, need, missing, improvement now, ours, in progress
    return T.join(["CR", "8192", "WHEAT", "bonus", str(x), str(y), "true" if improved else "false",
                   "BUILD_FARM", "", imp, "true" if ours else "false", building])


def state(*extra):
    return parse(SNAPSHOT + list(extra))


class ResourceLinesTest(unittest.TestCase):
    def test_statuses(self):
        text = summarize(state(resource(17, 18, improved=True, imp="FARM"),
                               resource(18, 18, building="BUILD_FARM:24576:3"),
                               resource(30, 30, ours=False), resource(16, 19)))
        self.assertIn("WHEAT (bonus) at (17,18) IMPROVED (FARM): done, nothing to build", text)
        self.assertIn("(18,18) BEING IMPROVED: worker 24576 is building BUILD_FARM (3 turns left)", text)
        self.assertIn("(30,30) OUTSIDE YOUR BORDERS", text)
        self.assertIn("(16,19) UNIMPROVED - BUILD_FARM possible now", text)

    def test_busy_worker_and_taken_targets(self):
        recs = (worker(24576, 18, 18, activity="1") + [T.join(["UW", "24576", "BUILD_FARM", "3"])]
                + worker(32770, 17, 17) + [T.join(["WT", "32770", "18", "18", "WHEAT", "BUILD_FARM", "1"]),
                                           T.join(["WT", "32770", "16", "19", "WHEAT", "BUILD_FARM", "2"])])
        text = summarize(state(*recs))
        self.assertIn("BUSY: building BUILD_FARM here, 3 turns left - leave it to finish", text)
        self.assertIn("WHEAT at (18,18) -> BUILD_FARM, 1 tiles away (TAKEN: worker 24576 is building BUILD_FARM there", text)
        # the opportunity points at the free tile, not the taken one
        self.assertIn("unit 32770 could build BUILD_FARM on WHEAT at (16,19)", text)


class JobsTest(unittest.TestCase):
    def setUp(self):
        self.jobs = WorkerJobs()

    def test_busy_worker_is_not_pulled_off_its_job(self):
        s = state(*worker(24576, 51, 20, activity="1"), T.join(["UW", "24576", "BUILD_MINE", "5"]))
        same = self.jobs.check("build_improvement", {"unit_id": 24576, "build": "BUILD_MINE", "x": 51, "y": 20}, s)
        self.assertTrue(same.startswith("ok: worker 24576 is already building BUILD_MINE"), same)
        other = self.jobs.check("build_improvement", {"unit_id": 24576, "build": "BUILD_MINE", "x": 49, "y": 18}, s)
        self.assertIn("is BUSY building BUILD_MINE at (51,20), 5 turns left", other)
        self.assertIn("BUSY", self.jobs.check("move_unit", {"unit_id": 24576, "x": 49, "y": 18}, s))
        self.assertIsNone(self.jobs.check("move_unit", {"unit_id": 24576, "x": 49, "y": 18}, s, replace=True))

    def test_done_job_is_refused_with_other_jobs(self):
        s = state(resource(17, 18, improved=True, imp="FARM"), *worker(32770, 17, 17),
                  T.join(["WT", "32770", "16", "19", "HORSE", "BUILD_PASTURE", "2"]))
        r = self.jobs.check("build_improvement", {"unit_id": 32770, "build": "BUILD_FARM", "x": 17, "y": 18}, s)
        self.assertIn("already IMPROVED (FARM): this job is DONE", r)
        self.assertIn("build_improvement BUILD_PASTURE at (16,19) on HORSE", r)
        # roads may still go on an improved tile
        self.assertIsNone(self.jobs.check("build_improvement",
                                          {"unit_id": 32770, "build": "BUILD_ROAD", "x": 17, "y": 18}, s))

    def test_tile_another_worker_has_is_refused(self):
        s = state(resource(53, 17, building="BUILD_PLANTATION:49154:2"), *worker(24576, 51, 17))
        r = self.jobs.check("build_improvement", {"unit_id": 24576, "build": "BUILD_PLANTATION", "x": 53, "y": 17}, s)
        self.assertIn("is TAKEN: worker 49154 is already building BUILD_PLANTATION there", r)

    def test_failed_build_is_not_retried_next_turn(self):
        s = state(*worker(24576, 50, 19))
        args = {"unit_id": 24576, "build": "BUILD_MINE", "x": 49, "y": 18}
        self.jobs.after("build_improvement", args, s,
                        "error: cannot build BUILD_MINE at (49,18): the tile is outside your borders")
        s["turn"] += 1
        r = self.jobs.check("build_improvement", args, s)
        self.assertIn("already failed on turn 12: the tile is outside your borders", r)
        s["turn"] += 10  # long enough for borders to have grown
        self.assertIsNone(self.jobs.check("build_improvement", args, s))

    def test_arrival_build_is_resumed_once_the_worker_is_idle_there(self):
        calls = []

        class Actions:
            def build_improvement(self, uid, build, x, y):
                calls.append((uid, build, x, y))
                return f"ok: UNIT_WORKER {uid} is building {build} at ({x},{y}) (about 9 turns)"

        s = state(*worker(24576, 50, 19))
        self.jobs.after("build_improvement", {"unit_id": 24576, "build": "BUILD_MINE", "x": 51, "y": 20}, s,
                        "ok: UNIT_WORKER 24576 now at (50,19), still heading to (51,20) on later turns; "
                        "it will build BUILD_MINE there on arrival")
        moving = state(*worker(24576, 50, 19, activity="1"))  # still on its way
        self.assertEqual(self.jobs.resume(moving, Actions()), [])
        arrived = state(*worker(24576, 51, 20))  # there, and idle
        done = self.jobs.resume(arrived, Actions())
        self.assertEqual(calls, [(24576, "BUILD_MINE", 51, 20)])
        self.assertIn("worker 24576 resumed its job: ok", done[0])
        self.assertEqual(self.jobs.pending, {})

    def test_another_order_cancels_the_pending_job(self):
        s = state(*worker(24576, 50, 19))
        self.jobs.after("build_improvement", {"unit_id": 24576, "build": "BUILD_MINE", "x": 51, "y": 20}, s,
                        "ok: ... it will build BUILD_MINE there on arrival")
        self.jobs.after("automate", {"unit_id": 24576, "kind": "build"}, s, "ok: automated")
        self.assertEqual(self.jobs.pending, {})

    def test_plan_naming_finished_tiles(self):
        s = state(resource(17, 18, improved=True, imp="FARM"), resource(16, 19))
        plan = "Now: build a farm on wheat at (17,18), then a farm at (16, 19)."
        self.assertEqual(WorkerJobs.stale_plan_tiles(plan, s), [(17, 18, "WHEAT", "FARM")])


if __name__ == "__main__":
    unittest.main()
