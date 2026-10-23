import { fireEvent, render, screen } from "@testing-library/react";

import { ChartCard } from "./charts";

test("every chart has a table view of its numbers", () => {
  render(
    <ChartCard
      title="Taxes"
      legend={[
        { label: "Federal", color: "#2a78d6", shape: "swatch" },
        { label: "State", color: "#eb6834", shape: "swatch" },
      ]}
      columns={["Year", "Federal", "State"]}
      rows={[[2026, 12345.6, 0]]}
    >
      <div>the plot</div>
    </ChartCard>,
  );
  expect(screen.getByText("the plot")).toBeTruthy();
  expect(screen.getByText("Federal")).toBeTruthy(); // the legend
  fireEvent.click(screen.getByRole("button", { name: "Table" }));
  expect(screen.queryByText("the plot")).toBeNull();
  expect(screen.getByRole("cell", { name: "12,346" })).toBeTruthy();
  expect(screen.getByRole("cell", { name: "2026" })).toBeTruthy();
});

test("a single series has no legend box", () => {
  render(
    <ChartCard title="One" legend={[{ label: "Only", color: "#2a78d6", shape: "line" }]} columns={["Year"]} rows={[]}>
      <div />
    </ChartCard>,
  );
  expect(screen.queryByText("Only")).toBeNull();
});
