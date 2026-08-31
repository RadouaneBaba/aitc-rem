/* Generated from schema/expectations.schema.json. Do not edit. */

/**
 * Where this sentence came from, and it is provenance for INTENT the way `Evidence` is provenance for observation.
 *
 * inferred  -- the model guessed and nobody has looked. Scenarios resting on one get @needs-review.
 * confirmed -- the tester read the guess and pressed the tick.
 * corrected -- the tester rewrote it. Theirs, word for word.
 * stated    -- taken verbatim from what they typed or said DURING the recording (an intent note, a narration segment, the objective). Never a guess.
 * rejected  -- the tester said this is NOT what should have happened. The strongest signal in the file: it means the recording contains a bug, and the author writes a bug report rather than a passing step.
 */
export type ExpectationSource = "inferred" | "confirmed" | "corrected" | "stated" | "rejected";
/**
 * Whether this is the thing the session was FOR, or a step on the way to it.
 *
 * Absent means `waypoint`, which is what every expectation written before this field existed was in practice.
 *
 * outcome  -- what the tester came to find out. There is usually one per objective, occasionally two. "the bag should total 49.50 for 10 Cinnamon Apple Crisp and 20 Pumpkin Spice Cake".
 * waypoint -- a checkable fact on the road to it. "the basket should show 10 capsules". Real, worth confirming, and not why anybody recorded anything.
 *
 * Every card used to be flat and equal, and a tester answering three of them never saw the sentence describing what they had actually set out to check. Their words for it: the objective says *check the bag shows the correct prices*, and what came back was a card per step result. The answer is not fewer cards -- a single vague card naming no value is exactly the expectation nobody can tick -- it is saying which one is the point.
 *
 * This orders the confirmation screen and nothing else. It does not gate authoring: a waypoint the tester confirms is as binding as an outcome they confirm, because both are the tester speaking.
 */
export type ExpectationRank = "outcome" | "waypoint";

/**
 * What SHOULD have happened, per action.
 *
 * The pipeline has two inputs and neither is an oracle. The recording says what the application DID -- by construction not an oracle. The objective names a feature rather than a behaviour: the real ones on disk read "check if filters are working correctly", and four of four such objectives produced a run the judge called bad. So a claim that can point at the retrieval that produced it can still only restate observed behaviour, and the tool is structurally incapable of producing a test that fails on the build it recorded.
 *
 * This file is the missing input. It is filled in three ways, cheapest first: the model guesses from the session, the tester confirms or corrects the guesses on one screen, and anything they said or marked during the recording is carried in verbatim. Guessing is fine -- testers are busy and clicking is cheap where writing is not.
 *
 * It belongs to the RECORDING, not to a run: it is an input to authoring, gathered once, and every later run of the same recording reads the same answers.
 */
export interface ExpectationSet {
  schemaVersion: "1.0";
  recordingId: string;
  createdAt: string;
  /**
   * When a human last answered the confirmation screen. Absent means nobody has: every expectation is still `inferred`, the run is still valid, and its scenarios carry @needs-review. Distinguishing 'never asked' from 'asked and agreed' is the whole point of storing it.
   */
  confirmedAt?: string;
  expectations: Expectation[];
}
/**
 * This interface was referenced by `ExpectationSet`'s JSON-Schema
 * via the `definition` "Expectation".
 */
export interface Expectation {
  /**
   * e.g. exp_003.
   */
  id: string;
  /**
   * The action(s) this is about. Usually one; a form filled across three fields and submitted is one intent and several events.
   */
  eventIds: string[];
  /**
   * What the tester did, in their language and the second person -- "You filtered by 'In stock'." This is the heading on the confirmation screen, so it has to be recognisable to someone who did it two minutes ago, not accurate to someone reading the trace.
   */
  action: string;
  /**
   * What SHOULD have happened. The oracle. One checkable sentence: "the list should drop from 24 products to 9", never "the filter should work".
   */
  expected: string;
  /**
   * What the recording shows actually happened. Kept beside `expected` because the confirmation screen shows both, and because when they disagree that disagreement IS the bug report -- 'expected 9 products, saw 24' is the same sentence either way.
   */
  observed?: string;
  source: ExpectationSource;
  rank?: ExpectationRank;
  /**
   * Path to the PNG for the event this is about, relative to the recording directory. The confirmation screen is pictures and two buttons; asking someone to read a semantic tree is how you get a screen nobody uses.
   */
  screenshot?: string;
  /**
   * Anything the tester added when correcting or rejecting. Free text, carried to the author untouched.
   */
  note?: string;
}
