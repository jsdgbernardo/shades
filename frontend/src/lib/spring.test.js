import { describe, expect, it } from "vitest";
import { isSettled, nearest, project, releaseVelocity, rubberband, springStep } from "./spring.js";

describe("sheet gesture physics", () => {
  it("projects a flick forward like scroll deceleration", () => {
    expect(project(0)).toBe(0);
    expect(project(1000)).toBeCloseTo(499, 0);
    expect(project(-1000)).toBeCloseTo(-499, 0);
  });

  it("snaps to the snap point nearest the projected endpoint", () => {
    // Released near the top (120 of 0..300) but flicked down fast: lands at the bottom.
    expect(nearest([0, 300], 120 + project(800))).toBe(300);
    expect(nearest([0, 300], 120 + project(0))).toBe(0);
  });

  it("resists progressively past a boundary", () => {
    const small = rubberband(20, 300);
    const large = rubberband(200, 300);
    expect(small).toBeLessThan(20);
    expect(large).toBeLessThan(200);
    expect(large / 200).toBeLessThan(small / 20);
  });

  it("critically damped spring settles on target without overshoot", () => {
    let state = { x: 0, v: 0 };
    let maxX = 0;
    for (let index = 0; index < 600 && !isSettled(state, 100); index += 1) {
      state = springStep(state, 100, 1 / 240, { damping: 1, response: 0.3 });
      maxX = Math.max(maxX, state.x);
    }
    expect(isSettled(state, 100)).toBe(true);
    expect(maxX).toBeLessThanOrEqual(100.5);
  });

  it("under-damped spring overshoots a little", () => {
    let state = { x: 0, v: 0 };
    let maxX = 0;
    for (let index = 0; index < 600; index += 1) {
      state = springStep(state, 100, 1 / 240, { damping: 0.8, response: 0.3 });
      maxX = Math.max(maxX, state.x);
    }
    expect(maxX).toBeGreaterThan(100);
    expect(maxX).toBeLessThan(110);
  });

  it("measures release velocity over the last 100 ms", () => {
    const samples = [{ t: 0, y: 0 }, { t: 50, y: 10 }, { t: 150, y: 60 }, { t: 200, y: 100 }];
    expect(releaseVelocity(samples)).toBeCloseTo(((100 - 60) / 50) * 1000, 0);
    expect(releaseVelocity([{ t: 0, y: 0 }])).toBe(0);
  });
});
