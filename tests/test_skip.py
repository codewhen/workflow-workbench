import asyncio

from release_workbench.application.starters import card
from tests.support import RunCase, sequence


class SkipCards(RunCase):
    async def waiting(self, run, card_id):
        for _ in range(200):
            entry = next(
                (
                    e
                    for e in run.evidence.state["executions"].values()
                    if e["card"] == card_id and e["status"] in {"running", "manual", "queued"}
                ),
                None,
            )
            if entry:
                return entry
            await asyncio.sleep(0.005)
        self.fail("Card did not become active")

    async def test_skip_current_wait_continues_run(self):
        run = self.make(sequence(card("slow", "wait", {"seconds": 20})))
        task = asyncio.create_task(run.execute())
        entry = await self.waiting(run, "slow")
        run.skip("main", "slow", entry["path"])
        self.assertEqual(await asyncio.wait_for(task, 3), 0)
        self.assertEqual(entry["status"], "skipped")
        self.assertEqual(entry["outcome"]["value"]["type"], "void")
        self.assertEqual(run.evidence.state["executions"]["root/main/finish"]["status"], "passed")

    async def test_skip_pending_card_does_not_execute_it(self):
        run = self.make(
            sequence(card("slow", "wait", {"seconds": 20}), card("later", "wait", {"seconds": 20}))
        )
        task = asyncio.create_task(run.execute())
        await self.waiting(run, "slow")
        run.skip("main", "later")
        run.skip("main", "slow")
        self.assertEqual(await asyncio.wait_for(task, 3), 0)
        self.assertEqual(run.evidence.state["executions"]["root/main/later"]["status"], "skipped")

    async def test_skip_manual_clears_request_and_preserves_evidence(self):
        run = self.make(
            sequence(card("approval", "manual", {"mode": "approval", "instructions": "Review"})),
            interactive=True,
        )
        task = asyncio.create_task(run.execute())
        entry = await self.waiting(run, "approval")
        run.skip("main", "approval")
        self.assertEqual(await asyncio.wait_for(task, 3), 0)
        self.assertEqual(entry["status"], "skipped")
        self.assertFalse(run.evidence.state["manual"])
        self.assertTrue(run.evidence.state["user_skips"])
        with self.assertRaises(ValueError):
            run.skip("main", "approval")

    async def test_control_cards_cannot_be_skipped(self):
        run = self.make(sequence(card("slow", "wait", {"seconds": 20})))
        task = asyncio.create_task(run.execute())
        await self.waiting(run, "slow")
        with self.assertRaises(ValueError):
            run.skip("main", "finish")
        run.stop()
        self.assertEqual(await asyncio.wait_for(task, 3), 130)

    async def test_skipping_workspace_stops_child_and_continues_parent(self):
        from release_workbench.infrastructure.documents import render_document

        (self.root / "child.yaml").write_text(
            render_document(sequence(card("hold", "wait", {"seconds": 20})))
        )
        run = self.make(sequence(card("child", "workspace", {"path": "child.yaml", "inputs": {}})))
        task = asyncio.create_task(run.execute())
        for _ in range(200):
            if run.children and run.children[0][1].busy:
                break
            await asyncio.sleep(0.005)
        run.skip("main", "child")
        self.assertEqual(await asyncio.wait_for(task, 3), 0)
        self.assertEqual(run.evidence.state["executions"]["root/main/child"]["status"], "skipped")
        self.assertFalse(run.children[0][1].busy)

    async def test_skipping_process_terminates_work_before_continuing(self):
        run = self.make(
            sequence(
                card(
                    "process",
                    "python",
                    {"code": "import time\ntime.sleep(20)\nreturn 1", "returns": "number"},
                )
            )
        )
        task = asyncio.create_task(run.execute())
        await self.waiting(run, "process")
        await asyncio.sleep(0.1)
        run.skip("main", "process")
        self.assertEqual(await asyncio.wait_for(task, 5), 0)
        self.assertEqual(run.evidence.state["executions"]["root/main/process"]["status"], "skipped")

    async def test_skipping_parallel_container_cancels_descendants(self):
        from release_workbench.application.starters import starter
        from tests.support import by_id

        raw = starter("Parallel skip", "parallel")
        for name in ("first", "second"):
            node = by_id(raw, name)
            node["kind"] = "wait"
            node["config"] = {"seconds": 20}
        run = self.make(raw)
        task = asyncio.create_task(run.execute())
        await self.waiting(run, "first")
        run.skip("main", "join")
        run.skip("main", "parallel")
        self.assertEqual(await asyncio.wait_for(task, 3), 0)
        self.assertEqual(
            run.evidence.state["executions"]["root/main/parallel"]["status"], "skipped"
        )
        self.assertTrue(
            all(
                e["status"] == "skipped"
                for e in run.evidence.state["executions"].values()
                if e["card"] in {"first", "second"}
            )
        )
