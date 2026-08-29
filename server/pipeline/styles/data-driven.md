Here is one good answer, on a different application, end to end.

The session index said:

    evt_001  click  link "Basket"                        | url -> /basket | +22 -0 ~0
             | "Total EUR 80.00"
    evt_002  input  textbox "Discount code" -> "SAVE10"  | +0 -0 ~1
    evt_003  click  button "Apply"                       | POST /api/discounts 200
             +1 -0 ~2 | "Discount applied" | "Total EUR 72.00"
    evt_004  input  textbox "Discount code" -> "SAVE25"  | +0 -0 ~1
    evt_005  click  button "Apply"                       | POST /api/discounts 200
             +0 -0 ~2 | "Total EUR 60.00"
    evt_006  input  textbox "Discount code" -> "EXPIRED5"| +0 -0 ~1
    evt_007  click  button "Apply"                       | POST /api/discounts 422
             +1 -0 ~1 | "This code has expired"
    evt_008  click  button "Checkout"                    | url -> /checkout | +40 -22 ~0
    evt_009  click  button "Pay now"                     | POST /api/orders 201
             +6 -2 ~1 | "Order 4471 confirmed"

The tester expected: "a discount code should recalculate the basket total", and
"an expired code should be refused".

What the author did, and it is the shape of the work rather than a number of
calls: it called `get_diff("evt_003")` and `get_diff("evt_005")` -- two
retrievals for what becomes ONE outline, because a table with a row nobody
retrieved is a test case somebody invented. It spent nothing on evt_002, evt_004
or evt_006, which are the tester typing. For the refusal it called
`get_network("evt_007")`: the page said "This code has expired", which is the
message, and the 422 is the behaviour -- and a status code that appears in the
session index but in no retrieval is not something you may claim. It then called
`get_snapshot("evt_007", "after")`, because the second verdict there is that
something is NOT on the page, and a whole-page retrieval is the only kind that
can support one.

It called `see("evt_005")` exactly once. `get_diff("evt_005")` came back with
two changed nodes reading "EUR 72.00" and "EUR 60.00" and the accessibility tree
said nothing about which was the live total and which was the old price kept
beside it; the question was not "what values are on the page" but "which of them
is the total now", and no text retrieval answers that. The screenshot showed
EUR 72.00 struck through. **The picture told it where to look; the claim below
still quotes a string a text retrieval returned.** Most sessions need no
screenshot at all.

```gherkin
Feature: Basket discount codes

  A discount code recalculates the basket total, and a code that is no longer
  valid is refused without changing what the customer owes.

  Scenario Outline: A valid discount code recalculates the basket total
    Given the basket totals EUR 80.00
    When the tester applies the discount code <code>
    Then the basket total becomes <total>

    Examples:
      | code   | total     |
      | SAVE10 | EUR 72.00 |
      | SAVE25 | EUR 60.00 |

  Scenario: An expired discount code is refused and nothing is applied
    When the tester applies the discount code "EXPIRED5"
    Then the code is refused with a 422 Unprocessable Entity
    And no discount is applied to the basket

  Scenario: Paying for a discounted basket confirms the order
    When the tester checks out and pays
    Then the order is confirmed as order 4471
```

```json
{
  "title": "Basket discount codes",
  "tags": [
    "basket",
    "discounts"
  ],
  "annotations": [
    {
      "kind": "step",
      "line": "the basket totals EUR 80.00",
      "id": "step_001",
      "role": "setup",
      "events": [
        "evt_001"
      ]
    },
    {
      "kind": "step",
      "line": "the tester applies the discount code <code>",
      "id": "step_002",
      "role": "test_step",
      "events": [
        "evt_002",
        "evt_003",
        "evt_004",
        "evt_005"
      ]
    },
    {
      "kind": "verdict",
      "line": "the basket total becomes <total>",
      "evidence": {
        "eventId": "evt_005",
        "literal": "Total EUR 60.00"
      }
    },
    {
      "kind": "step",
      "line": "the tester applies the discount code \"EXPIRED5\"",
      "id": "step_003",
      "role": "test_step",
      "events": [
        "evt_006",
        "evt_007"
      ]
    },
    {
      "kind": "verdict",
      "line": "the code is refused with a 422 Unprocessable Entity",
      "evidence": {
        "eventId": "evt_007",
        "literal": "422",
        "kind": "network"
      }
    },
    {
      "kind": "verdict",
      "line": "no discount is applied to the basket",
      "evidence": {
        "eventId": "evt_007",
        "literal": "Discount applied",
        "predicate": {
          "form": "absent"
        }
      }
    },
    {
      "kind": "step",
      "line": "the tester checks out and pays",
      "id": "step_004",
      "role": "test_step",
      "events": [
        "evt_008",
        "evt_009"
      ]
    },
    {
      "kind": "verdict",
      "line": "the order is confirmed as order 4471",
      "evidence": {
        "eventId": "evt_009",
        "literal": "Order 4471 confirmed"
      }
    }
  ],
  "omitted": []
}
```

Seven things in that answer are worth copying.

**The unit is the flow, and the values go in the table.** Three applications of
a discount code is not three scenarios. It is one behaviour the tester exercised
with different inputs, and writing it out three times produces a transcript of a
session rather than a test somebody designed. This is the whole of this style:
when the same flow repeats with different values, it is an outline.

**Every row is a repetition the recording actually contains.** SAVE10 and
SAVE25 are in the table because the tester typed them and the author retrieved
what each one did. **Nothing in the gate can check this.** The verdict cites
evt_005 and "Total EUR 60.00", which proves the second row; the first row rests
on the author having gone and looked. A third row invented to round the table
out -- SAVE50, EUR 40.00 -- would pass every validator in the system and be
fiction. That is the one failure mode this style has and the other two do not,
so the rule is absolute: **a row you cannot name the events for does not go in
the table.**

**The outline's step carries the events of every row.** step_002 lists all four
-- evt_002 through evt_005 -- because `event_coverage` counts each recorded
event once per test case and an outline is one test case. Do not attach a row's
events to a row; there is nowhere to put them and the coverage check will say
so.

**Two rows minimum.** One row is not a table, it is a scenario carrying extra
ceremony. A flow that happened once gets a plain `Scenario`, which is why paying
for the order is written out normally: it happened once, so there is nothing to
parameterise and no honest second row to write.

**The expired code is NOT a row.** It is the same control with a different
value, which is exactly the trap: a table is one behaviour with several inputs,
and "the total is recalculated" and "the request is refused" are two behaviours.
Forced into one table it needs a `<total>` column with nothing to put in it, and
the verdict stops being true of every row -- which is the only thing an outline
promises.

**The 422 is cited from `get_network`, and the absence from a snapshot.** The
session index prints status codes and the index is a SUMMARY, so a claim resting
on it points at nothing. And "no discount is applied" is a claim about the whole
page: a `find_text` that returns no matches proves that this retrieval found
nothing, not that the page is clear, so `absent` is evaluated against a
`get_snapshot` or it cannot be evaluated at all.

**Values are exact, and they are the application's wording.** "EUR 72.00", not
"the discounted total"; "422", not "an error". A table exists to make the values
the subject of the test, so a table of vague values is the worst of both styles.
