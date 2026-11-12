import { BAND_LOOK, BANDS, isBand } from "./band";

describe("band", () => {
  it("names every band in words", () => {
    expect(BANDS.map((b) => BAND_LOOK[b].label)).toEqual(["Low", "Moderate", "High"]);
  });

  it("does not know the old words or inherited keys", () => {
    for (const old of ["exceedance", "elevated", "acceptable", "above", "near", "below", "toString", "", null, 3]) {
      expect(isBand(old)).toBe(false);
    }
  });
});
