import { inBasis } from "./runViews";

test("real values divide by the price level", () => {
  const buckets = { price_level: [1, 2, null], net_worth: [100, 300, 5] };
  expect(inBasis(buckets, "net_worth", "nominal")).toEqual([100, 300, 5]);
  expect(inBasis(buckets, "net_worth", "real")).toEqual([100, 150, null]);
  expect(inBasis(buckets, "missing", "real")).toEqual([]);
});
