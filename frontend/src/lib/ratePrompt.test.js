import { describe, expect, it } from "vitest";
import { forgetRated, myRating, rememberRated, ratedStreets, streetsToRate } from "./ratePrompt.js";
import { edgeAt } from "./nav.js";

const edge = (way_id, length_m, name = `Street ${way_id}`, named = true) => ({ way_id, name, named, length_m, edge_key: `${way_id}:${length_m}` });

function memoryStorage() {
  const data = new Map();
  return { getItem: (key) => data.get(key) ?? null, setItem: (key, value) => data.set(key, String(value)) };
}

describe("streets to rate after a walk", () => {
  const edges = [edge(1, 120), edge(2, 40), edge(1, 80), edge(3, 20), edge(4, 300), edge(5, 90, "Footway", false)];

  it("groups a street's pieces and lists the longest first", () => {
    expect(streetsToRate(edges, 10_000).map((s) => [s.way_ids, s.length_m])).toEqual([[[4], 300], [[1], 200], [[2], 40]]);
  });

  it("treats the pieces of one named street as one street", () => {
    const pieces = [edge(11, 100, "Katipunan Avenue"), edge(12, 150, "Katipunan Avenue"), edge(13, 60, "Aurora Boulevard")];
    expect(streetsToRate(pieces, 10_000)).toEqual([
      { name: "Katipunan Avenue", way_ids: [11, 12], length_m: 250 },
      { name: "Aurora Boulevard", way_ids: [13], length_m: 60 },
    ]);
    // A rated piece is left out; the rest of the street is still asked about.
    expect(streetsToRate(pieces, 10_000, new Set([11]))[0]).toEqual({ name: "Katipunan Avenue", way_ids: [12], length_m: 150 });
  });

  it("counts only the walked part of the route", () => {
    // 150 m walked: 120 m of street 1, then 30 m of street 2.
    expect(streetsToRate(edges, 150).map((s) => [s.way_ids, s.length_m])).toEqual([[[1], 120], [[2], 30]]);
    expect(streetsToRate(edges, 0)).toEqual([]);
  });

  it("leaves out short, unnamed and already rated streets, and keeps to the limit", () => {
    const ids = streetsToRate(edges, 10_000, new Set([4])).flatMap((s) => s.way_ids);
    expect(ids).toEqual([1, 2]);
    expect(ids).not.toContain(3); // 20 m
    expect(ids).not.toContain(5); // unnamed footway
    expect(streetsToRate(edges, 10_000, new Set(), 1)).toHaveLength(1);
    expect(streetsToRate(undefined, 100)).toEqual([]);
  });
});

describe("remembering rated streets on the phone", () => {
  it("stores and reads way ids", () => {
    const storage = memoryStorage();
    rememberRated(7, {}, storage);
    rememberRated(9, {}, storage);
    rememberRated(7, {}, storage);
    expect([...ratedStreets(storage)]).toEqual([7, 9]);
  });

  it("keeps each rating and its token, and forgets a removed one", () => {
    const storage = memoryStorage();
    rememberRated(7, { rating: 2, token: "a" }, storage);
    rememberRated(7, { rating: 4 }, storage); // changed: the token stays
    expect(myRating(7, storage)).toEqual({ rating: 4, token: "a" });
    expect(myRating(8, storage)).toBeNull();
    forgetRated(7, storage);
    expect(myRating(7, storage)).toBeNull();
    expect(ratedStreets(storage).size).toBe(0);
  });

  it("still reads the older list of rated ids", () => {
    const storage = memoryStorage();
    storage.setItem("shades.ratedStreets", JSON.stringify([5, 6]));
    expect([...ratedStreets(storage)]).toEqual([5, 6]);
    expect(myRating(5, storage)).toEqual({});
  });

  it("copes with blocked or broken storage", () => {
    const blocked = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
    expect(() => rememberRated(7, {}, blocked)).not.toThrow();
    expect(() => forgetRated(7, blocked)).not.toThrow();
    expect(ratedStreets(blocked).size).toBe(0);
    expect(ratedStreets({ getItem: () => "not json" }).size).toBe(0);
    expect(ratedStreets(null).size).toBe(0);
  });
});

describe("the edge being walked", () => {
  const distances = [0, 100, 150, 400];
  const edges = [edge(1, 100), edge(2, 50), edge(3, 250)];

  it("finds the edge at a distance along the route", () => {
    expect(edgeAt(edges, distances, 0)).toBe(edges[0]);
    expect(edgeAt(edges, distances, 99)).toBe(edges[0]);
    expect(edgeAt(edges, distances, 100)).toBe(edges[1]);
    expect(edgeAt(edges, distances, 399)).toBe(edges[2]);
    expect(edgeAt(edges, distances, 1000)).toBe(edges[2]);
    expect(edgeAt([], distances, 10)).toBeNull();
  });
});
