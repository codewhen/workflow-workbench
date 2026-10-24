import { test, expect } from "@playwright/test";

for (const display of ["list", "canvas"] as const) {
  test(`reveals a failed card after browsing away in ${display}`, async ({
    page,
    request,
  }) => {
    await page.goto("/workspace");
    const headers = {
      "X-Workbench-Token": (await page
        .locator('meta[name="workbench-token"]')
        .getAttribute("content"))!,
    };
    const entry = await (
      await request.post("/api/create", {
        headers,
        data: { filename: `failure-${display}.yaml`, name: "Failure focus" },
      })
    ).json();
    const saved = await (
      await request.get(`/api/config?workflow=${entry.id}`)
    ).json();
    const cards = [
      { id: "start", kind: "start", name: "Start" },
      { id: "wait", kind: "wait", name: "Wait", config: { seconds: 1 } },
      ...Array.from({ length: 12 }, (_, i) => ({
        id: `step-${i}`,
        kind: "wait",
        name: `Step ${i}`,
        config: { seconds: 0 },
      })),
      {
        id: "failure",
        kind: "python",
        name: "Failing operation",
        config: { code: 'raise ValueError("Expected failure")' },
      },
      { id: "finish", kind: "finish", name: "Finish" },
    ];
    saved.workflow.layout = {};
    saved.workflow.graphs.main = {
      cards,
      edges: cards.slice(1).map((c, i) => ({
        id: `edge-${i}`,
        source: cards[i].id,
        target: c.id,
        kind: "flow",
        source_port: "next",
        target_port: "entry",
      })),
    };
    expect(
      (
        await request.post(`/api/save?workflow=${entry.id}`, {
          headers,
          data: { workflow: saved.workflow, revision: saved.revision },
        })
      ).ok(),
    ).toBeTruthy();
    await page.goto(`/workflows/${entry.id}/run/${display}`);
    await page.getByRole("button", { name: "Run all", exact: true }).click();
    const node = (id: string) =>
      page.locator(
        display === "list"
          ? `.list-card[data-card-id="${id}"]`
          : `.react-flow__node[data-id="${id}"]`,
      );
    await node("start").click();
    await expect
      .poll(
        async () =>
          (await (await request.get(`/api/state?workflow=${entry.id}`)).json())
            .status,
      )
      .toBe("failed");
    if (display === "list")
      await expect(node("failure")).toHaveAttribute("aria-pressed", "true");
    else
      await expect(node("failure").locator(".flow-card")).toHaveClass(/chosen/);
    await expect(node("failure")).toBeInViewport();
    await expect(
      page.getByRole("heading", { name: "Failing operation", exact: true }),
    ).toBeVisible();
    if (display === "canvas")
      await page
        .getByRole("button", { name: "Fit workflow", exact: true })
        .click();
    await node("start").click();
    await page.waitForTimeout(700);
    if (display === "list")
      await expect(node("start")).toHaveAttribute("aria-pressed", "true");
    else
      await expect(node("start").locator(".flow-card")).toHaveClass(/chosen/);
  });
}
