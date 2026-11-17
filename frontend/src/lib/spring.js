// Gesture physics for the bottom sheet, following SKILL.md (Apple's fluid-interface rules):
// springs described by damping ratio + response, momentum projection, rubber-banding.

/** Where a flick would come to rest (Apple's projection, d ≈ 0.998 like scrolling). */
export function project(velocity, deceleration = 0.998) {
  return ((velocity / 1000) * deceleration) / (1 - deceleration);
}

/** Progressive resistance past a boundary instead of a hard stop. */
export function rubberband(overshoot, dimension, constant = 0.55) {
  if (dimension <= 0) return 0;
  return (overshoot * dimension * constant) / (dimension + constant * Math.abs(overshoot));
}

export function nearest(points, value) {
  return points.reduce((best, point) => (Math.abs(point - value) < Math.abs(best - value) ? point : best), points[0]);
}

/** One semi-implicit Euler step of a unit-mass spring with Apple-style parameters. */
export function springStep(state, target, dt, { damping = 1, response = 0.3 } = {}) {
  const stiffness = (2 * Math.PI / response) ** 2;
  const friction = (4 * Math.PI * damping) / response;
  const acceleration = -stiffness * (state.x - target) - friction * state.v;
  const v = state.v + acceleration * dt;
  return { x: state.x + v * dt, v };
}

export function isSettled(state, target) {
  return Math.abs(state.x - target) < 0.5 && Math.abs(state.v) < 5;
}

/**
 * Animate from the current (presentation) value toward a target, starting with the
 * gesture's velocity. Returns a cancel function so a new touch can interrupt at any time.
 */
export function animateSpring({ from, to, velocity = 0, damping = 1, response = 0.3, onUpdate, onDone }) {
  let state = { x: from, v: velocity };
  let last = null;
  let frame = 0;
  const tick = (time) => {
    const dt = last === null ? 1 / 60 : Math.min((time - last) / 1000, 1 / 20);
    last = time;
    // Substeps keep a stiff spring stable on slow frames.
    const steps = Math.max(1, Math.ceil(dt / (1 / 240)));
    for (let index = 0; index < steps; index += 1) state = springStep(state, to, dt / steps, { damping, response });
    if (isSettled(state, to)) {
      onUpdate(to);
      onDone?.();
      return;
    }
    onUpdate(state.x);
    frame = requestAnimationFrame(tick);
  };
  frame = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(frame);
}

/** Release velocity in px/s from recent pointer samples [{ t, y }]. */
export function releaseVelocity(samples) {
  if (samples.length < 2) return 0;
  const last = samples[samples.length - 1];
  const first = samples.find((sample) => last.t - sample.t <= 100) ?? samples[0];
  const elapsed = (last.t - first.t) / 1000;
  return elapsed > 0 ? (last.y - first.y) / elapsed : 0;
}
