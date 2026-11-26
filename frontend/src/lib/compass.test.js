import { describe, expect, it } from "vitest";
import { angleDiff, headingFromEvent, smoothHeading } from "./compass.js";

describe("compass", () => {
  it("reads the iPhone compass heading as is", () => {
    expect(headingFromEvent({ webkitCompassHeading: 90 })).toBe(90);
    expect(headingFromEvent({ webkitCompassHeading: 0, alpha: 123, absolute: true })).toBe(0);
  });

  it("turns Android's counterclockwise alpha into a clockwise heading", () => {
    expect(headingFromEvent({ absolute: true, alpha: 90 })).toBe(270);
    expect(headingFromEvent({ absolute: true, alpha: 0 })).toBe(0);
  });

  it("ignores readings without an absolute direction", () => {
    expect(headingFromEvent({ absolute: false, alpha: 90 })).toBeNull();
    expect(headingFromEvent({ webkitCompassHeading: -1 })).toBeNull();
    expect(headingFromEvent({})).toBeNull();
  });

  it("corrects for a landscape screen", () => {
    expect(headingFromEvent({ webkitCompassHeading: 350 }, 90)).toBe(80);
    expect(headingFromEvent({ absolute: true, alpha: 90 }, 270)).toBe(180);
  });

  it("smooths across north without spinning the long way round", () => {
    const step = smoothHeading(350, 10, 0.5);
    expect(angleDiff(step, 0)).toBeLessThan(0.001);
    expect(smoothHeading(null, 370)).toBe(10);
    expect(smoothHeading(100, 120, 1)).toBeCloseTo(120);
  });

  it("measures the shorter angle between headings", () => {
    expect(angleDiff(359, 1)).toBe(2);
    expect(angleDiff(90, 270)).toBe(180);
    expect(angleDiff(-10, 10)).toBe(20);
  });
});
