import { cell, compactMoney, money, percent, signedMoney } from "./format";

test("money", () => {
  expect(money(1234567.8)).toBe("$1,234,568");
  expect(compactMoney(1_234_567)).toBe("$1.23M");
  expect(compactMoney(45_600)).toBe("$45.6K");
  expect(compactMoney(250_000)).toBe("$250K");
  expect(compactMoney(-2_500_000)).toBe("-$2.5M");
  expect(compactMoney(null)).toBe("–");
  expect(signedMoney(1500)).toBe("+$1.5K");
});

test("percent and cells", () => {
  expect(percent(0.875)).toBe("87.5%");
  expect(cell(2026)).toBe("2026");
  expect(cell(123456.7)).toBe("123,457");
  expect(cell(0.22)).toBe("0.22");
  expect(cell("single")).toBe("single");
});
