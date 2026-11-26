import { describe, expect, it } from "vitest";
import { isTrain, rideSteps, walkedSoFar, walkingPart } from "./legs.js";

const walk = (distance_m, tag) => ({ type: "walk", distance_m, geometry: [[0, 0], [tag, tag]], exposure: { sections: [] }, edges: [{ tag }] });
const ride = {
  type: "ride", from: "Katipunan", to: "Ortigas",
  segments: [
    { line_name: "LRT Line 2", from: "Katipunan", to: "Araneta Center - Cubao" },
    { line_name: "MRT Line 3", from: "Araneta Center - Cubao", to: "Ortigas" },
  ],
  transfers: [{ from: "Araneta Center - Cubao", to: "Araneta Center - Cubao", to_line: "MRT Line 3" }],
};
const train = { kind: "train", legs: [walk(380, 1), ride, walk(150, 2)] };

describe("train trips during a walk", () => {
  it("guides one walking part at a time", () => {
    expect(isTrain(train)).toBe(true);
    expect(walkingPart(train, 0).edges).toEqual([{ tag: 1 }]);
    expect(walkingPart(train, 1)).toBeNull();
    expect(walkingPart(train, 2).edges).toEqual([{ tag: 2 }]);
    const plain = { id: "shortest", geometry: [] };
    expect(walkingPart(plain, 2)).toBe(plain);
    expect(isTrain(plain)).toBe(false);
  });

  it("counts the walked distance across both walks", () => {
    expect(walkedSoFar(train, 0, 200)).toBe(200);
    expect(walkedSoFar(train, 0, 999)).toBe(380);
    expect(walkedSoFar(train, 1, 50)).toBe(380);
    expect(walkedSoFar(train, 2, 100)).toBe(480);
    expect(walkedSoFar({ kind: "walk" }, 0, 70)).toBe(70);
  });

  it("reads the ride as steps without ride times", () => {
    expect(rideSteps(ride)).toEqual([
      "Ride LRT Line 2 from Katipunan to Araneta Center - Cubao",
      "Change at Araneta Center - Cubao to MRT Line 3",
      "Then ride MRT Line 3 from Araneta Center - Cubao to Ortigas",
      "Get off at Ortigas",
    ]);
    expect(rideSteps(ride).join(" ")).not.toMatch(/min/);
  });
});
