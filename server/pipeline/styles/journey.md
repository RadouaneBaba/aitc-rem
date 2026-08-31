Here is one good answer, on a different application, end to end.

The session index said:

    evt_001  click  button "United Kingdom"                 | url -> /?country=GB | +8 -0 ~2
    evt_002  click  link "Spring Milk Chocolate Praline Biscuits"
             | url -> /spring-milk-chocolate-praline-biscuits | +214 -180 ~0
             | "Spring Milk Chocolate Praline Biscuits" | "£12.95"
    evt_003  click  button "Add to Bag"                     | POST /api/basket 200
             +6 -0 ~2 | "Added to your basket" | "Basket (1 item)"
             tester: assertion -> "Added to your basket" (generic, containing
             "Added to your basket Spring Milk Chocolate Praline Biscuits £12.95
             View & Checkout Continue Shopping")
    evt_004  click  link "View & Checkout"                  | url -> /basket | +90 -60 ~0
             | "Subtotal £12.95" | "Total £16.90"
             tester: assertion -> "Total £16.90" (span, mark 1)
             tester: assertion -> "Subtotal £12.95" (span, mark 2)
             -- THE TESTER MARKED 2 ELEMENTS AT THIS MOMENT. ... --
    evt_005  click  button "Proceed to Checkout"            | url -> /checkout/login | +30 -20 ~0
             | "Checkout as guest" | "Sign in" | "Create an account"
    evt_006  click  button "Checkout as guest"              | +12 -2 ~1
    evt_007  input  textbox "Email"    -> "<<user_email_1>>" | +0 -0 ~1
    evt_008  input  textbox "Postcode" -> "SW1A 1AA"         | +0 -0 ~1
    evt_009  click  button "Continue to delivery options"   | POST /api/addresses 201
             +9 -1 ~2 | "Your address was successfully added!"
    evt_010  click  radio  "Standard delivery"              | +0 -0 ~3 | "£4.95"
    evt_011  input  textbox "Gift message" -> "Happy birthday" | +0 -0 ~1
    evt_012  click  button "Continue to Payment"            | +14 -6 ~2
             | "Happy birthday" | "Grand Total £17.90"
    evt_013  click  button "Pay Securely Now"               | POST /api/orders 201
             | url -> /order/confirmed | +40 -30 ~0 | "Order FM-40518 confirmed"
    evt_014  click  link "Shopping Basket"                  | url -> /basket
             | +18 -74 ~0 | "Your basket is empty"

The tester expected: "a guest order should total the item plus delivery, and the
gift message should survive to the order".

What the author did, and it is the shape of the work rather than a number of
calls. It called `get_diff("evt_004")`, because the tester had marked two
elements there and a mark is the top of the provenance ladder -- the diff showed
`Subtotal £12.95` and `Total £16.90` in the same response, which is what makes
the RELATION between them checkable rather than either number alone. It called
`get_snapshot("evt_012", "after")` for the gift message and the grand total,
which is one retrieval answering two verdicts at the end of the journey. It
called `get_network("evt_013")`: the page says "Order FM-40518 confirmed", which
is the message, and the 201 is the behaviour, and a status code that appears in
the session index but in no retrieval is not something you may claim. For the
last scenario it called `get_snapshot("evt_014", "after")`, because that verdict
is that something is NOT on the page and only a whole-page retrieval can support
one.

It called `see("evt_012")` exactly once, and only because the text would not
settle the question it was actually asking. That snapshot carries `Total £16.90`
and `Grand Total £17.90` and the accessibility tree names neither as the amount
being charged -- one is the basket total carried forward and one includes
delivery, and binding the wrong one would have shipped a verdict that is true of
a build where delivery is never added. The screenshot showed `Grand Total
£17.90` in the pay panel beside the button. **The picture told it which one to
quote; the claim below still quotes a string a text retrieval returned.** Most
journeys need no screenshot at all.

It spent nothing at all on evt_006 through evt_011. Those are the tester filling
in a form, and nothing about them was in doubt.

```gherkin
Feature: Guest checkout

  A guest can order a product, choose delivery, add a gift message, and pay --
  and the order that results is the one they built.

  @Automated @Smoke @Checkout
  Scenario Outline: A guest orders <product> and pays for it

    # find the product and put it in the basket
    Given the tester is on the storefront with <country> selected
    When the tester opens the product page for <product>
    And the tester adds it to the basket
    Then the basket is offered with the product in it

    # the basket totals what was added, plus delivery
    When the tester opens the basket
    Then the subtotal is the product's own price of <price>

    # check out as a guest
    When the tester proceeds to checkout as a guest
    And the tester enters their delivery address
    Then the address is accepted

    # delivery, gifting, and the total they are asked to pay
    When the tester chooses <delivery> delivery and adds the gift message <message>
    And the tester continues to payment
    Then the gift message is carried through to the order as <message>
    And the grand total is <total>

    # pay
    When the tester pays
    Then the order is created with a 201
    And the order confirmation names the order

    Examples:
      | country        | product                                       | price  | delivery | message        | total  |
      | United Kingdom | Spring Milk Chocolate Praline Biscuits        | £12.95 | Standard | Happy birthday | £17.90 |

  @Automated @Checkout
  Scenario: Placing the order empties the basket
    When the tester opens the basket again
    Then the ordered product is no longer in it
```

```json
{
  "title": "Guest checkout",
  "tags": [
    "Automated",
    "Smoke",
    "Checkout"
  ],
  "annotations": [
    {
      "kind": "step",
      "line": "the tester is on the storefront with <country> selected",
      "id": "step_001",
      "role": "setup",
      "events": [
        "evt_001"
      ]
    },
    {
      "kind": "step",
      "line": "the tester opens the product page for <product>",
      "id": "step_002",
      "role": "setup",
      "events": [
        "evt_002"
      ]
    },
    {
      "kind": "step",
      "line": "the tester adds it to the basket",
      "id": "step_003",
      "role": "test_step",
      "events": [
        "evt_003"
      ]
    },
    {
      "kind": "verdict",
      "line": "the basket is offered with the product in it",
      "evidence": {
        "eventId": "evt_003",
        "literal": "Basket (1 item)"
      }
    },
    {
      "kind": "step",
      "line": "the tester opens the basket",
      "id": "step_004",
      "role": "test_step",
      "events": [
        "evt_004"
      ]
    },
    {
      "kind": "verdict",
      "line": "the subtotal is the product's own price of <price>",
      "evidence": {
        "eventId": "evt_004",
        "literal": "Subtotal £12.95"
      }
    },
    {
      "kind": "step",
      "line": "the tester proceeds to checkout as a guest",
      "id": "step_005",
      "role": "test_step",
      "events": [
        "evt_005",
        "evt_006"
      ]
    },
    {
      "kind": "step",
      "line": "the tester enters their delivery address",
      "id": "step_006",
      "role": "test_step",
      "events": [
        "evt_007",
        "evt_008",
        "evt_009"
      ]
    },
    {
      "kind": "verdict",
      "line": "the address is accepted",
      "evidence": {
        "eventId": "evt_009",
        "literal": "Your address was successfully added!"
      }
    },
    {
      "kind": "step",
      "line": "the tester chooses <delivery> delivery and adds the gift message <message>",
      "id": "step_007",
      "role": "test_step",
      "events": [
        "evt_010",
        "evt_011"
      ]
    },
    {
      "kind": "step",
      "line": "the tester continues to payment",
      "id": "step_008",
      "role": "test_step",
      "events": [
        "evt_012"
      ]
    },
    {
      "kind": "verdict",
      "line": "the gift message is carried through to the order as <message>",
      "evidence": {
        "eventId": "evt_012",
        "literal": "Happy birthday"
      }
    },
    {
      "kind": "verdict",
      "line": "the grand total is <total>",
      "evidence": {
        "eventId": "evt_012",
        "literal": "Grand Total £17.90"
      }
    },
    {
      "kind": "step",
      "line": "the tester pays",
      "id": "step_009",
      "role": "test_step",
      "events": [
        "evt_013"
      ]
    },
    {
      "kind": "verdict",
      "line": "the order is created with a 201",
      "evidence": {
        "eventId": "evt_013",
        "literal": "201",
        "kind": "network"
      }
    },
    {
      "kind": "verdict",
      "line": "the order confirmation names the order",
      "evidence": {
        "eventId": "evt_013",
        "literal": "Order FM-40518 confirmed"
      }
    },
    {
      "kind": "step",
      "line": "the tester opens the basket again",
      "id": "step_010",
      "role": "test_step",
      "events": [
        "evt_014"
      ]
    },
    {
      "kind": "verdict",
      "line": "the ordered product is no longer in it",
      "evidence": {
        "eventId": "evt_014",
        "literal": "Spring Milk Chocolate Praline Biscuits",
        "predicate": {
          "form": "absent"
        }
      }
    }
  ],
  "omitted": []
}
```

Ten things in that answer are worth copying.

**One scenario for the whole journey.** Browse, basket, checkout, delivery,
gifting, payment. It is one behaviour because it reaches one outcome -- an order
exists and is the one the tester built -- and every verdict on the way is a
checkpoint on the road to it, not a separate test. Cut this into five scenarios
and four of them open with set-up that is really another test's body, which is
how a suite ends up with tests that cannot run on their own.

Length is not the thing to judge. Ask what the scenario ESTABLISHES. Two
unrelated outcomes under one heading is two test cases sharing a name, however
short; a long walk to one outcome is one test case, however long.

**And a second scenario where the outcome is genuinely different.** *Placing the
order empties the basket* is not a checkpoint on the way to the first outcome --
it is a separate promise the application makes, and it stays true or false
independently. Two scenarios, because there are two things being established;
not five, because the other steps establish nothing on their own.

It is a plain `Scenario:` because there is nothing in it that identifies WHICH
item in a way the test should vary. A one-row table there would be ceremony.

**Every value that identifies WHICH item goes in the table.** `<product>`,
`<country>`, `<delivery>`, `<message>`. The application has a million products
and this is a test of checkout, not of the biscuits: written with the product
name in the prose it reads as a transcript of one afternoon, and the next person
cannot run it against anything else.

`<price>` and `<total>` are in the table too, and they are the interesting case
-- they are values the tester's own row DETERMINES. Change the product and both
change with it, so they belong beside it, and the verdict line stays a sentence
about the feature: *the subtotal is the product's own price*.

**But the literal in the evidence is the concrete string, always.** The line
says `<price>` and the evidence says `Subtotal £12.95`. That is not a
contradiction and it is the whole mechanism: the line is what a reader and an
automation engineer see, and the literal is what the gate re-checks against the
stored response. A `<placeholder>` as a literal proves nothing, because no page
ever said `<price>`.

**An `Examples` row is not permission to drop the events of the other pass.**
This is the one way an outline goes wrong, and it is easy to miss because the
prose reads perfectly. If the tester did the flow twice -- sorted high to low,
then low to high -- the outline has two rows and its steps must still account
for BOTH passes' events. Every recorded event lands in exactly one step's
`events` or in `omitted` with a reason, and a table row is neither.

So a two-row outline over a session like this:

    evt_002  click  combobox "Sort by"
    evt_003  select combobox "Sort by" -> "Price High-Low"
    evt_005  click  div.refinement-tabs
    evt_006  click  combobox "Sort by"
    evt_007  select combobox "Sort by" -> "Price Low-High"

annotates its one `When` line with all of them, not just the first pass:

    {"kind": "step", "line": "the tester sorts the products by <order>",
     "id": "step_002", "role": "test_step",
     "events": ["evt_002", "evt_003", "evt_005", "evt_006", "evt_007"]}

An event you cannot place is an `omitted` entry naming it -- *"a stray click on
the filter bar that changed nothing"* -- and never a silence.

**Section comments, where the journey turns.** `# find the product and put it
in the basket`. A forty-line scenario is unreadable without them and they cost
nothing -- Gherkin ignores them and so does the annotation join. Use them for
the phases of the journey, never for a note about one step.

**The subtotal verdict quotes the phrase, not the number.** `Subtotal £12.95`
rather than `£12.95`. The bare number is also the product's price, is on the
product page, is probably in a recommendation carousel, and would keep the test
green on a build where the subtotal stopped being calculated. The phrase around
the value is what makes the check about the subtotal.

**Two marks at one moment are one claim about their relation.** The tester
marked the subtotal and the total together at evt_004; that is them saying the
thing under test is how those two relate, not either number. Here it produced a
subtotal verdict tied to the product's own price and a grand-total verdict tied
to the row -- so changing `<product>` changes both, and a build that stopped
adding delivery fails. Quoting only one of them would have passed either way.

**One retrieval answered two verdicts.** `get_snapshot("evt_012", "after")`
carries the gift message and the grand total, because they were on screen
together. Retrieve per QUESTION, not per verdict.

**The negative claim says `absent`, and cites the page it is about.** *"The
ordered product is no longer in it"* cannot be proved by quoting a string,
because the string is not there. `absent` names the whole-page retrieval it is
about and the checker confirms nothing in it says the product. Written without
the predicate it would be a sentence saying GONE resting on a check that only
says PRESENT, which is true of no page and therefore proves nothing at all.

**`see` was called once, at the one moment the text did not answer the
question.** Two plausible totals in one snapshot and no name distinguishing
them. Not to confirm something already readable -- a screenshot costs about a
thousand tokens and an author that looks at every event is not investigating.
Most journeys need none.

**`@Automated @Smoke @Checkout` on the scenario.** Tags are how a suite is
selected and a scenario is what gets selected, so they belong there. Say what
the scenario is FOR, not what it does -- the name already says that.

**The form-filling is one step, and the tester's own typing is not asserted on.**
`the tester enters their delivery address` covers three events, because that is
one thing a person does and one step definition somebody will write. The verdict
underneath is the application's answer -- *the address is accepted* -- and never
the values that were typed: a field showing what was put into it is true on
every build.
