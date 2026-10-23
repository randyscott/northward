import { claimAge } from "./ScenarioPage";

test("claiming ages read as written", () => {
  expect(claimAge(70)).toBe("70");
  expect(claimAge({ years: 67, months: 6 })).toBe("67 and 6 months");
  expect(claimAge({ years: 66, months: 1 })).toBe("66 and 1 month");
  expect(claimAge({ years: 62 })).toBe("62");
});
