// The balance grid saves one revision of accounts.yaml with only the balances changed (comments and layout intact),
// and the document's history shows the change and can restore the old revision.
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

import { freshWorkspace, startServer } from "./server";

const ACCOUNTS = join(
  resolve(dirname(fileURLToPath(import.meta.url)), "..", ".."),
  "data",
  "profiles",
  "example",
  "accounts.yaml",
);

test("update balances, then diff and restore them", async ({ page }) => {
  const server = await startServer(freshWorkspace({ example: true }), 8798);
  try {
    await page.goto(`${server.url}/profiles/example/balances`);
    const balance = page.getByLabel("joint_brokerage balance");
    await expect(balance).toHaveValue("150,000");
    await balance.fill("175,000");
    await page.getByLabel("joint_brokerage cost basis").fill("abc");
    await expect(page.getByRole("button", { name: /^Save/ })).toBeDisabled(); // not a number
    await page.getByLabel("joint_brokerage cost basis").fill("120000");
    await expect(page.getByText("+$25K").first()).toBeVisible();
    await page.getByRole("button", { name: "Save 1 change" }).click();
    await expect(page.getByText(/Saved as revision 2/)).toBeVisible();

    const saved = (await (await fetch(`${server.url}/api/profiles/example/documents/accounts`)).json()) as {
      yaml_text: string;
      latest: { note: string };
    };
    const original = readFileSync(ACCOUNTS, "utf8");
    expect(saved.latest.note).toBe("Updated balances");
    expect(saved.yaml_text).toBe(
      original.replace("balance: 150000\n    cost_basis: 110000", "balance: 175000\n    cost_basis: 120000"),
    ); // only those two values changed; every comment is still there

    await page.goto(`${server.url}/profiles/example/documents/accounts`);
    await page.getByRole("tab", { name: /History/ }).click();
    await expect(page.locator(".monaco-diff-editor")).toBeVisible();
    await expect(page.locator(".monaco-diff-editor")).toContainText("175000");
    await page.getByText("seeded from").click();
    await page.getByRole("button", { name: "Restore revision 1" }).click();
    await expect(page.getByText("Restored as revision 3.")).toBeVisible();
    await page.goto(`${server.url}/profiles/example/balances`);
    await expect(page.getByLabel("joint_brokerage balance")).toHaveValue("150,000");
  } finally {
    await server.stop();
  }
});
