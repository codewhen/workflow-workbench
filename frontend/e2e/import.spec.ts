import { test, expect } from "@playwright/test";

test("Open YAML preserves the original path and restores manifest children", async ({
  page,
  request,
}) => {
  await page.goto("/workspace");
  const headers = {
    "X-Workbench-Token": (await page
      .locator('meta[name="workbench-token"]')
      .getAttribute("content"))!,
  };
  const child = await (
    await request.post("/api/create", {
      headers,
      data: { filename: "import-child.yaml", name: "Imported child" },
    })
  ).json();
  const parent = await (
    await request.post("/api/create", {
      headers,
      data: { filename: "import-root.yaml", name: "Imported root" },
    })
  ).json();
  const saved = await (
    await request.get(`/api/config?workflow=${parent.id}`)
  ).json();
  saved.workflow.library = {
    folder: "Example",
    imports: ["import-child.yaml"],
  };
  expect(
    (
      await request.post(`/api/save?workflow=${parent.id}`, {
        headers,
        data: { workflow: saved.workflow, revision: saved.revision },
      })
    ).ok(),
  ).toBeTruthy();
  for (const entry of [parent, child])
    expect(
      (
        await request.post(`/api/remove?workflow=${entry.id}`, {
          headers,
          data: {},
        })
      ).ok(),
    ).toBeTruthy();
  await page.route("**/api/pick-file", (route) =>
    route.fulfill({ json: { path: saved.path } }),
  );
  await page.reload();
  await page.getByRole("button", { name: "Open YAML", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/workflows/${parent.id}(/|$)`));
  const library = await (await request.get("/api/library")).json();
  expect(
    library.entries.some((e: { id: string }) => e.id === child.id),
  ).toBeTruthy();
  expect(
    library.entries.find((e: { id: string }) => e.id === parent.id).path,
  ).toBe(saved.path);
  expect(
    (await (await request.get(`/api/state?workflow=${parent.id}`)).json()).busy,
  ).toBe(false);
  expect(
    (await (await request.get(`/api/config?workflow=${parent.id}`)).json())
      .workflow,
  ).toEqual(saved.workflow);
});
