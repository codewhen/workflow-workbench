import { test, expect } from "@playwright/test";

for (const display of ["list", "canvas"] as const) {
  test(`skip menu is discoverable and works in ${display}`, async ({
    page,
    request,
  }) => {
    await page.goto("/workspace");
    const token = await page
      .locator('meta[name="workbench-token"]')
      .getAttribute("content");
    const headers = { "X-Workbench-Token": token! };
    const entry = await (
      await request.post("/api/create", {
        headers,
        data: { filename: `skip-${display}.yaml`, name: "Skip test" },
      })
    ).json();
    const saved = await (
      await request.get(`/api/config?workflow=${entry.id}`)
    ).json();
    saved.workflow.layout = {};
    saved.workflow.graphs.main = {
      cards: [
        { id: "start", kind: "start", name: "Start" },
        {
          id: "current",
          kind: "wait",
          name: "Current wait",
          config: { seconds: 60 },
        },
        {
          id: "later",
          kind: "wait",
          name: "Later wait",
          config: { seconds: 60 },
        },
        { id: "finish", kind: "finish", name: "Finish" },
      ],
      edges: [
        ["start", "current"],
        ["current", "later"],
        ["later", "finish"],
      ].map(([source, target]) => ({
        id: source + target,
        source,
        target,
        source_port: "next",
        target_port: "entry",
        kind: "flow",
      })),
    };
    const response = await request.post(`/api/save?workflow=${entry.id}`, {
      headers,
      data: { workflow: saved.workflow, revision: saved.revision },
    });
    expect(response.ok()).toBeTruthy();
    await page.goto(`/workflows/${entry.id}/run/${display}`);
    const card = (id: string) =>
      page.locator(
        display === "list"
          ? `.list-card[data-card-id="${id}"]`
          : `.react-flow__node[data-id="${id}"]`,
      );
    await card("later").click({ button: "right" });
    await page.getByRole("menuitem", { name: "Mark to skip" }).click();
    await expect(
      page.getByRole("region", { name: "Review card skip" }),
    ).toBeVisible();
    const highlighted =
      display === "list" ? card("later") : card("later").locator(".flow-card");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    if (display === "canvas")
      await page
        .locator(".react-flow__pane")
        .click({ position: { x: 20, y: 20 } });
    else await card("current").click();
    await expect(
      page.getByRole("region", { name: "Review card skip" }),
    ).toBeVisible();
    await expect(highlighted).toHaveClass(/skip-preview/);
    await expect(highlighted).toHaveCSS("animation-name", "skip-pulse");
    await page.emulateMedia({ reducedMotion: "reduce" });
    await expect(highlighted).toHaveCSS("animation-name", "none");
    await page.screenshot({
      path: `/private/tmp/workbench-skip-${display}-preview-desktop.png`,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({
      path: `/private/tmp/workbench-skip-${display}-preview-mobile.png`,
    });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.emulateMedia({ reducedMotion: "no-preference" });

    await page.keyboard.press("Escape");
    await expect(
      page.getByRole("region", { name: "Review card skip" }),
    ).toHaveCount(0);
    if (display === "canvas")
      await page
        .getByRole("button", { name: "Flowchart", exact: true })
        .click();

    expect(
      (await (await request.get(`/api/config?workflow=${entry.id}`)).json())
        .workflow.skip_cards,
    ).toBeUndefined();
    await card("later").click({ button: "right" });
    await page.getByRole("menuitem", { name: "Mark to skip" }).click();
    await page
      .getByRole("button", { name: "Confirm skip", exact: true })
      .click();
    await expect(
      card("later").getByText("Marked to skip", { exact: true }),
    ).toBeVisible();
    await page.reload();
    await expect(
      card("later").getByText("Marked to skip", { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Run all", exact: true }).click();
    await expect
      .poll(
        async () =>
          (await (await request.get(`/api/state?workflow=${entry.id}`)).json())
            .executions["root/main/current"]?.status,
      )
      .toBe("running");
    await card("current").click();
    await page
      .getByRole("button", { name: "Skip this card", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "Review card skip" }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Confirm skip", exact: true })
      .click();
    await expect
      .poll(
        async () =>
          (await (await request.get(`/api/state?workflow=${entry.id}`)).json())
            .status,
      )
      .toBe("passed");
    const state = await (
      await request.get(`/api/state?workflow=${entry.id}`)
    ).json();
    expect(state.executions["root/main/current"].status).toBe("skipped");
    expect(state.executions["root/main/later"].status).toBe("skipped");
    await expect(
      page.getByText("This run does not verify the full workflow.", {
        exact: false,
      }),
    ).toBeVisible();
    await card("later").click({ button: "right" });
    await page
      .getByRole("menuitem", { name: "Unmark for future runs" })
      .click();
    await page
      .getByRole("button", { name: "Confirm unmark", exact: true })
      .click();
    await expect(
      card("later").getByText("Marked to skip", { exact: true }),
    ).toHaveCount(0);
    expect(
      (await (await request.get(`/api/state?workflow=${entry.id}`)).json())
        .executions["root/main/later"].status,
    ).toBe("skipped");
    await page.screenshot({
      path: `/private/tmp/workbench-skip-${display}-desktop.png`,
    });
    await page.keyboard.press("Escape");
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({
      path: "/private/tmp/workbench-skip-mobile.png",
      fullPage: true,
    });
  });
}
