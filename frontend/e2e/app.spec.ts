// Phase 9A's "done when": create a profile, edit a lever, run Monte Carlo, and compare two scenarios entirely in the
// browser, and find all of it still there after restarting the app.
import { expect, type Page, test } from "@playwright/test";

import { freshWorkspace, type Server, startServer } from "./server";

/** Replace the editor's whole text (pasting, so the editor's autocomplete can't rewrite typed keys). */
async function setEditorText(page: Page, text: string) {
  await page.evaluate((t) => navigator.clipboard.writeText(t), text);
  await page.locator(".monaco-editor .view-lines").click();
  await page.keyboard.press("ControlOrMeta+A");
  await page.keyboard.press("ControlOrMeta+V");
}

/** The same path on another server (after a restart). */
const on = (server: Server, url: string) => url.replace(/^http:\/\/[^/]+/, server.url);

test("create, edit, run, compare, and restart", async ({ browser }) => {
  const workspace = freshWorkspace();
  let server = await startServer(workspace);
  try {
    const context = await browser.newContext({
      baseURL: server.url,
      permissions: ["clipboard-read", "clipboard-write"],
    });
    const page = await context.newPage();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));

    // Create a profile from the blank template.
    await page.goto("/");
    await expect(page).toHaveURL(/\/profiles$/);
    await page.getByRole("button", { name: "New profile" }).click();
    await page.getByLabel("Name", { exact: true }).fill("e2e_household");
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page.getByRole("heading", { name: "e2e_household" })).toBeVisible();

    // Clone the base scenario, then change a lever in the clone: claim Social Security at 70.
    await page.getByRole("button", { name: "Clone" }).first().click();
    await page.getByLabel("New scenario name").fill("claim_at_70");
    await page.getByRole("dialog").getByRole("button", { name: "Clone" }).click();
    await expect(page).toHaveURL(/scenarios\/claim_at_70$/);
    await page.getByRole("link", { name: "Edit scenario" }).click();
    await expect(page.locator(".monaco-editor")).toBeVisible();

    const year = new Date().getFullYear();
    const scenario = (levers: string) =>
      `schema_version: 1\ndescription: "Claim at 70"\nhorizon:\n  start_year: ${year}\n  end_age: 95\n${levers}`;
    // The schema catches an unknown key as you type...
    await setEditorText(page, scenario("not_a_lever: 1\n"));
    await expect(page.locator(".squiggly-error, .squiggly-warning").first()).toBeVisible();
    // ...and saving shows the server's cross-document problems, marked on the line they point at.
    await setEditorText(page, scenario("levers:\n  ss_claim_ages:\n    nobody: 70\n"));
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.locator(".notice.error")).toContainText("unknown member 'nobody'");
    await expect(page.locator(".squiggly-error").first()).toBeVisible();
    await setEditorText(page, scenario("levers:\n  ss_claim_ages:\n    me: 70\n"));
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Saved revision 2.")).toBeVisible();

    // Run Monte Carlo on the clone and see the dashboard.
    await page.getByRole("link", { name: "Run this scenario" }).click();
    await page.getByLabel("Paths", { exact: true }).fill("200");
    await page.getByRole("button", { name: "Run Monte Carlo" }).click();
    await expect(page.getByTestId("success-probability")).toBeVisible({ timeout: 120_000 });
    await expect(page.getByRole("region", { name: "Balances by account type" })).toBeVisible();
    const runUrl = page.url();

    // Compare the two scenarios.
    await page.getByRole("link", { name: "Compare scenarios" }).click();
    await page.getByLabel("Paths", { exact: true }).fill("200");
    await page.getByRole("checkbox", { name: /^base/ }).check();
    await page.getByRole("checkbox", { name: /^claim_at_70/ }).check();
    await page.getByRole("button", { name: "Compare 2 scenarios" }).click();
    await expect(page.getByRole("region", { name: "Median net worth" })).toBeVisible({ timeout: 120_000 });
    const compareUrl = page.url();

    // Restart the app: everything is still there.
    await server.stop();
    server = await startServer(workspace);
    await page.goto(`${server.url}/profiles/e2e_household`);
    await expect(page.getByRole("link", { name: "claim_at_70" }).first()).toBeVisible();
    await page.goto(`${server.url}/profiles/e2e_household/documents/scenarios/claim_at_70`);
    await expect(page.getByText("revision 2 ·")).toBeVisible();
    await page.goto(on(server, runUrl));
    await expect(page.getByTestId("success-probability")).toBeVisible();
    await page.goto(`${server.url}/runs`);
    // The clone's run, and base's: comparing reused the clone's identical run instead of running it again.
    await expect(page.locator("tbody").getByRole("link", { name: /^#\d+$/ })).toHaveCount(2);
    await page.goto(on(server, compareUrl));
    await expect(page.getByRole("region", { name: "Median net worth" })).toBeVisible(); // stored runs, no rerun

    expect(errors).toEqual([]);
  } finally {
    await server.stop();
  }
});
