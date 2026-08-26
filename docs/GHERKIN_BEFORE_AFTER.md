# What the Gherkin looked like, before and after

`runs/` is gitignored and is deleted between milestones, so this file is the
only durable record of what the pipeline actually produced. Each section is a
snapshot: the full feature text for every recording, plus the numbers that say
whether it was honest as well as readable.

Read a grounding rate beside a yield, always. A configuration that claims
nothing scores 1.0.

The recording ids differ between the two halves for the fixtures, and that is
not a mistake: `pnpm e2e` re-records them through the real extension and the
recorder mints a new id each time. The two commercial recordings —
`rec_MT7MXBS9B2VB` and `rec_MT7VTN7ZRJPO` — keep their ids and are the honest
comparison, because they are the same bytes run through two versions of the
pipeline.

---

## The short version

**`rec_MT7MXBS9B2VB`**, 34 events, no annotations and no narration — what a
tester's first recording actually looks like. Before, one scenario, three
near-duplicate beats under a heading that described what the tester *did*:

```gherkin
Scenario: Hamper size upgrades automatically as items are added
  Given the tester navigates to the "Create Your Own Hamper" page
  When the tester adds items until the hamper reaches its capacity
  Then the hamper is shown as a "Small Wicker Basket" with a capacity of "5 / 5"
  When the tester continues adding items to trigger an upgrade to a Medium Wicker Basket
  Then the hamper is shown as a "Medium Wicker Basket" with a capacity of "13 / 13"
  When the tester continues adding items to trigger an upgrade to a Large Wicker Basket
  Then the hamper is shown as a "Large Wicker Basket" with a capacity of "18 / 18"
```

After, two test cases, each named for what it *proves*, each with one verdict,
each with the shared setup lifted into a `Background`:

```gherkin
Scenario: A hamper automatically upgrades to a Medium Wicker Basket when capacity is reached
Scenario: A hamper automatically upgrades to a Large Wicker Basket when capacity is reached
```

The split was not a prompt change. `split.py` triggered on *33 events in one
scenario, over the floor of 12*, and the deterministic net took the answer whole.

The `checkout` fixture is the one to read for `Background`: it produced two
scenarios on one attempt and one on another, and both shapes are correct. What
was NOT correct is that the run directory held all three feature files at once
— a filename carries the scenario number, so a re-run with a different number of
test cases left the old documents beside the new ones, downloadable and
indistinguishable. `_write_output` clears them now.

**`rec_MT7VTN7ZRJPO`** closed its scenario on *the shopping bag panel opens,
displaying the item(s) previously added to the cart* — the navigation assertion
the drafting prompt forbids in bold, bound to the panel's own heading, past
thirteen validators. That claim is refused now. The scenario ends on an action
instead, with `gherkin_style` warning about it: a visible gap rather than an
invisible falsehood. Which is worse to ship is a real question, and the answer
here is the second one.

Across all nine recordings the gate now reads **7 clean, 2 warned, 0 rejected**,
and 44 of 44 accepted claims resolve to a retrieval whose stored response still
contains the literal. Both warnings are phrasing a reviewer fixes in the UI in
seconds — a verdict with two passing states, and a scenario that ends on an
action because binding refused the only claim offered for its last step.

**The ablation**, seven fixtures, first measured run of the rebuilt generator:

| | A1 before | A1 after | A2 before | A2 after |
|---|---|---|---|---|
| accepted expected results | 9 | **14** | 7 | **12** |
| Yield | 0.45 | **0.61** | 0.35 | **0.52** |
| ValidFin | 0.987 | 0.973 | 0.959 | **1.000** |
| Calls/step | 0.8 | **2.04** | 1.1 | **2.74** |
| Spread | 0.0 | **1.05** | 0.50 | 0.71 |

Three things to read there. A2's final gate score used to go *down* — the repair
loop replacing proven claims with unprovable ones — and now reaches 1.0. A1's
`Spread` used to be 0.0, which CLAUDE.md flagged as the sign that retrieval had
become decoration; it is 1.05. And yield rose by about a third **while** two new
refusals (`_unwitnessed`, `_existence_only`) were deleting claims.

`Converged` fell to 0.111, and that number is not what it looks like: five of
the seven surviving critic findings are `coherence`, which has no repair route
by design. The loop never started on four of the seven runs because there was
nothing it was allowed to touch.

---

## Before — STATUS.md defects unfixed — 2026-08-25 22:53 UTC

18 recording(s), newest run of each.

### `rec_devtools_demo` — Sign in and add a widget

`runs/rec_devtools_demo/imp_001`

| | |
|---|---|
| scenarios | 1 |
| steps | 2 |
| events covered | 4 |
| accepted expected results | 0 |
| grounding rate | 1.0 |
| validator pass (first / final) | 0.75 / — |
| critic findings raised | — |
| tool calls total | 15 |
| tool calls per step | `{'step_001': 3, 'step_002': 4, 'step_003': 3, 'step_004': 0}` |
| rejected by | *nothing* |
| warned by | gherkin_style, mutation_claimed |

```gherkin
# aitc-rem - rec_devtools_demo - 2026-08-20 - evidence: tc_rec_devtools_demo.trace.md

@shopping @cart
Feature: Widget management

  A registered user can successfully add a specific widget to their shopping
  cart.

  Scenario: A user adds a widget to their cart
    Given the tester signs in as "<<user_email_1>>" with "<<password>>"
    When the tester adds the "Blue Widget" to the cart
```

### `rec_MSYWWF2M9EW5` — Check that an order over EUR500 requires approval

`runs/rec_MSYWWF2M9EW5/abl_A2_rec_MSYWWF2M9EW5`

| | |
|---|---|
| scenarios | 1 |
| steps | 4 |
| events covered | 10 |
| accepted expected results | 2 |
| grounding rate | 1.0 |
| validator pass (first / final) | 1.0 / 1.0 |
| critic findings raised | 0 |
| tool calls total | 3 |
| tool calls per step | `{'step_002': 1, 'step_004': 1}` |
| rejected by | *nothing* |
| warned by | *nothing* |

```gherkin
# aitc-rem - rec_MSYWWF2M9EW5 - 2026-08-25 - evidence: tc_rec_MSYWWF2M9EW5.trace.md

@orders @approval @needs-review
Feature: Order approval

  Orders exceeding a specific monetary threshold require manager approval to
  be processed.

  Scenario: An order over EUR500 requires manager approval
    Given the tester signs in as "<<user_email_1>>" and adds a "Blue Widget" to the cart
    When the tester proceeds to checkout and sets the order total to "615"
    Then the application displays an alert that "Orders over EUR500 require approval"

    When the tester attempts to place the order without approval
    And the tester confirms manager approval and submits the order
    Then the order is confirmed with an "Order confirmed" alert
```

### `rec_MSYWWJBVQOM8` — Exercise the awkward parts of the checkout page

`runs/rec_MSYWWJBVQOM8/run_001`

| | |
|---|---|
| scenarios | 1 |
| steps | 4 |
| events covered | 10 |
| accepted expected results | 1 |
| grounding rate | 1.0 |
| validator pass (first / final) | 0.9090909090909091 / 1.0 |
| critic findings raised | 4 |
| tool calls total | 4 |
| tool calls per step | `{'step_004': 1, 'step_001': 0, 'step_003': 0}` |
| rejected by | *nothing* |
| warned by | *nothing* |

```gherkin
# aitc-rem - rec_MSYWWJBVQOM8 - 2026-08-25 - evidence: tc_rec_MSYWWJBVQOM8.trace.md

@checkout @needs-review
Feature: Checkout process

  Exercise the checkout page functionality including payment saving and
  validation.

  Scenario: User completes checkout steps
    Given the tester authenticates as "<<user_email_1>>" and proceeds to the checkout page
    When the tester selects "Express (next day, +EUR12)" delivery
    And the tester saves the payment method
    And the tester submits the order for slow validation
    Then the message "Validating with the finance system..." is shown
```

### `rec_MSYYTZIYT749` — login and add two elements to the cart

`runs/rec_MSYYTZIYT749/site_001`

| | |
|---|---|
| scenarios | 1 |
| steps | 6 |
| events covered | 7 |
| accepted expected results | 1 |
| grounding rate | 1.0 |
| validator pass (first / final) | 0.875 / — |
| critic findings raised | — |
| tool calls total | 7 |
| tool calls per step | `{'step_001': 1, 'step_002': 2, 'step_003': 1, 'step_004': 1, 'step_005': 2, 'step_006': 0}` |
| rejected by | *nothing* |
| warned by | mutation_claimed |

```gherkin
# Generated by aitc-rem from recording rec_MSYYTZIYT749 - 2026-08-18
# Objective: login and add two elements to the cart
# Steps marked !! need human review.
# warn: 7 event(s) flagged network_incomplete
# warn: 3 event(s) flagged no_accessible_name
# warn: 1 event(s) flagged rapid_sequence

Feature: login and add two elements to the cart

  Scenario: login and add two elements to the cart
    When the tester enters the username !!
      # evt_001 - !network_incomplete - !no_accessible_name

    When the tester enters the password into the password field !!
      # evt_002 - !network_incomplete - !no_accessible_name

    When the tester logs in to the application !!
      # evt_003 - !rapid_sequence - !network_incomplete

    When the tester adds two items to the cart !!
      # evt_004, evt_005 - !network_incomplete
    Then the cart badge displays the number 2
      # evidence: evt_005 - tc_0005 - inferred - '2'

    When the tester navigates to the cart page !!
      # evt_006 - !network_incomplete - !no_accessible_name

    When the tester proceeds to checkout !!
      # evt_007 - !network_incomplete


  # Parameters (from redaction - supply real values before running):
  #   <<password>>  (password)
```

### `rec_MT1VY7C2ZWFW` — Check that adding an item updates the cart badge

`runs/rec_MT1VY7C2ZWFW/abl_A2_rec_MT1VY7C2ZWFW`

| | |
|---|---|
| scenarios | 1 |
| steps | 2 |
| events covered | 4 |
| accepted expected results | 1 |
| grounding rate | 1.0 |
| validator pass (first / final) | 1.0 / 1.0 |
| critic findings raised | 0 |
| tool calls total | 2 |
| tool calls per step | `{'step_002': 1}` |
| rejected by | *nothing* |
| warned by | *nothing* |

```gherkin
# aitc-rem - rec_MT1VY7C2ZWFW - 2026-08-25 - evidence: tc_rec_MT1VY7C2ZWFW.trace.md

@cart
Feature: Cart management

  Adding items to the cart updates the cart badge.

  Scenario: Adding an item updates the cart badge
    Given the tester signs in to the application
    When the tester adds a widget to the cart
    Then the cart badge displays "Cart contains 1 items"
```

### `rec_MT24JRPBEL95` — Check the cart badge, then that a large order needs approval

`runs/rec_MT24JRPBEL95/run_001`

| | |
|---|---|
| scenarios | 1 |
| steps | 3 |
| events covered | 8 |
| accepted expected results | 1 |
| grounding rate | 1.0 |
| validator pass (first / final) | 1.0 / 1.0 |
| critic findings raised | 0 |
| tool calls total | 2 |
| tool calls per step | `{'step_003': 1}` |
| rejected by | *nothing* |
| warned by | *nothing* |

```gherkin
# aitc-rem - rec_MT24JRPBEL95 - 2026-08-25 - evidence: tc_rec_MT24JRPBEL95.trace.md

@orders @approval @needs-review
Feature: Order approval

  Orders exceeding a specific total value require manager approval.

  Scenario: An order exceeding the threshold requires approval
    Given the tester signs in as "<<user_email_1>>"
    When the tester adds a "Blue Widget" to the cart and proceeds to checkout
    And the tester attempts to place an order with a total of "900" EUR
    Then the system displays an alert stating "Orders over EUR500 require approval"
```

### `rec_MT26NN4Q090Y` — Check that an order over EUR500 requires approval

`runs/rec_MT26NN4Q090Y/abl_A2_rec_MT26NN4Q090Y`

| | |
|---|---|
| scenarios | 1 |
| steps | 4 |
| events covered | 7 |
| accepted expected results | 2 |
| grounding rate | 1.0 |
| validator pass (first / final) | 1.0 / 1.0 |
| critic findings raised | 0 |
| tool calls total | 8 |
| tool calls per step | `{'step_003': 1, 'step_004': 6}` |
| rejected by | *nothing* |
| warned by | *nothing* |

```gherkin
# aitc-rem - rec_MT26NN4Q090Y - 2026-08-25 - evidence: tc_rec_MT26NN4Q090Y.trace.md

@orders @approval @needs-review
Feature: Order approval

  Orders exceeding a specific monetary threshold require manager approval.

  Scenario: An order over EUR500 cannot be placed without approval
    Given the tester logs into the application
    When the tester adds an item to the cart and proceeds to checkout
    And the tester sets the order total to an amount over "500" EUR
    Then the application displays an alert that orders over EUR500 require approval

    When the tester tries to place the order
    Then the order submission is rejected with an approval required error

    # 2 exploratory action(s) omitted - navigated to reports and back to the catalog. See the review UI.
```

### `rec_MT77MABWW6VH` — Check that an order over EUR500 requires approval

`runs/rec_MT77MABWW6VH/run_001`

| | |
|---|---|
| scenarios | 1 |
| steps | 3 |
| events covered | 6 |
| accepted expected results | 1 |
| grounding rate | 1.0 |
| validator pass (first / final) | 1.0 / 1.0 |
| critic findings raised | 0 |
| tool calls total | 4 |
| tool calls per step | `{'step_003': 1}` |
| rejected by | *nothing* |
| warned by | *nothing* |

```gherkin
# aitc-rem - rec_MT77MABWW6VH - 2026-08-25 - evidence: tc_rec_MT77MABWW6VH.trace.md

@orders @needs-review
Feature: Order approval

  An order over EUR500 requires manager approval.

  Scenario: An order over EUR500 cannot be placed without approval
    Given the tester logs into the application
    When the tester navigates to the checkout page
    And the tester tries to place an order with a total of "600"
    Then the application displays an alert stating "Orders over EUR500 require approval"
```

### `rec_MT7EYKIKMXY0` — Check that an order can be exported after approval

`runs/rec_MT7EYKIKMXY0/run_001`

| | |
|---|---|
| scenarios | 1 |
| steps | 3 |
| events covered | 6 |
| accepted expected results | 1 |
| grounding rate | 1.0 |
| validator pass (first / final) | 1.0 / 1.0 |
| critic findings raised | 0 |
| tool calls total | 2 |
| tool calls per step | `{'step_003': 1}` |
| rejected by | *nothing* |
| warned by | *nothing* |

```gherkin
# aitc-rem - rec_MT7EYKIKMXY0 - 2026-08-25 - evidence: tc_rec_MT7EYKIKMXY0.trace.md

@orders @export @needs-review
Feature: Order export

  An order can be exported after it has been approved.

  Scenario: Exporting an order fails with an internal server error
    Given the tester signs in as "<<user_email_1>>"
    When the tester adds a "Blue Widget" to the cart and proceeds to checkout
    And the tester attempts to export the order
    Then the export fails with an "Internal server error"
```

### `rec_MT7MXBS9B2VB` — check if hamper sizes change correctly

`runs/rec_MT7MXBS9B2VB/run_001`

| | |
|---|---|
| scenarios | 1 |
| steps | 4 |
| events covered | 33 |
| accepted expected results | 3 |
| grounding rate | 1.0 |
| validator pass (first / final) | 1.0 / 1.0 |
| critic findings raised | 0 |
| tool calls total | 4 |
| tool calls per step | `{'step_002': 1, 'step_003': 1, 'step_004': 1}` |
| rejected by | *nothing* |
| warned by | *nothing* |

```gherkin
# aitc-rem - rec_MT7MXBS9B2VB - 2026-08-25 - evidence: tc_rec_MT7MXBS9B2VB.trace.md

@hampers
Feature: Hamper size management

  The hamper size automatically upgrades when the number of items exceeds the
  current basket's capacity

  Scenario: Hamper size upgrades automatically as items are added
    Given the tester navigates to the "Create Your Own Hamper" page
    When the tester adds items until the hamper reaches its capacity
    Then the hamper is shown as a "Small Wicker Basket" with a capacity of "5 / 5"

    When the tester continues adding items to trigger an upgrade to a Medium Wicker Basket
    Then the hamper is shown as a "Medium Wicker Basket" with a capacity of "13 / 13"

    When the tester continues adding items to trigger an upgrade to a Large Wicker Basket
    Then the hamper is shown as a "Large Wicker Basket" with a capacity of "18 / 18"

    # 1 abandoned action(s) omitted - the tester closed the final notification after reaching the maximum hamper size. See the review UI.
```

### `rec_MT7VTN7ZRJPO` — Adding items to the shopping cart

`runs/rec_MT7VTN7ZRJPO/run_001`

| | |
|---|---|
| scenarios | 1 |
| steps | 3 |
| events covered | 5 |
| accepted expected results | 2 |
| grounding rate | 1.0 |
| validator pass (first / final) | 0.875 / 1.0 |
| critic findings raised | 2 |
| tool calls total | 7 |
| tool calls per step | `{'step_002': 1, 'step_003': 2}` |
| rejected by | *nothing* |
| warned by | *nothing* |

```gherkin
# aitc-rem - rec_MT7VTN7ZRJPO - 2026-08-25 - evidence: tc_rec_MT7VTN7ZRJPO.trace.md

@shopping_cart
Feature: Shopping cart

  Adding items to the shopping cart

  Scenario: The shopping cart enforces maximum quantity limits
    Given the tester is on the coffee capsules page
    When the tester attempts to add more than the allowed quantity of a capsule
    Then an error message indicating that the maximum quantity has been exceeded is displayed

    When the tester opens the shopping bag
    Then the shopping bag panel opens, displaying the item(s) previously added to the cart
```

### `rec_MT8TEM57CRGS` — Check that an order over EUR500 requires approval

`runs/rec_MT8TEM57CRGS/run_001`

| | |
|---|---|
| scenarios | 1 |
| steps | 5 |
| events covered | 10 |
| accepted expected results | 3 |
| grounding rate | 1.0 |
| validator pass (first / final) | 1.0 / 1.0 |
| critic findings raised | 0 |
| tool calls total | 9 |
| tool calls per step | `{'step_003': 1, 'step_004': 6, 'step_005': 1}` |
| rejected by | *nothing* |
| warned by | *nothing* |

```gherkin
# aitc-rem - rec_MT8TEM57CRGS - 2026-08-25 - evidence: tc_rec_MT8TEM57CRGS.trace.md

@orders @approval
Feature: Order approval

  Orders exceeding a specific monetary threshold require manager approval
  before they can be placed

  Scenario: An order over EUR500 requires manager approval
    Given the tester signs in to the application
    When the tester adds an item to the cart and proceeds to checkout
    And the tester sets the order total to "615"
    Then an alert "Orders over EUR500 require approval" is displayed

    When the tester tries to place the order without approval
    Then the order is rejected with an approval required status

    When the tester confirms manager approval and places the order
    Then the order is confirmed
```

### `rec_MT8TEQCKCCNT` — Exercise the awkward parts of the checkout page

`runs/rec_MT8TEQCKCCNT/abl_A2_rec_MT8TEQCKCCNT`

| | |
|---|---|
| scenarios | 1 |
| steps | 3 |
| events covered | 10 |
| accepted expected results | 2 |
| grounding rate | 1.0 |
| validator pass (first / final) | 0.9090909090909091 / 0.9090909090909091 |
| critic findings raised | 3 |
| tool calls total | 16 |
| tool calls per step | `{'step_002': 1, 'step_003': 6}` |
| rejected by | mutation_claimed |
| warned by | *nothing* |

```gherkin
# aitc-rem - rec_MT8TEQCKCCNT - 2026-08-25 - evidence: tc_rec_MT8TEQCKCCNT.trace.md

@checkout @needs-review
Feature: Checkout validation

  The checkout process involves payment method saving and finance system
  validation.

  Scenario: A user can save a payment method and submit for validation
    Given the tester signs in as "<<user_email_1>>" and navigates to the checkout page
    When the tester selects "Express (next day, +EUR12)" delivery and submits the payment method.
    Then the checkout page updates to reflect the selected Express delivery fee and the payment method is accepted

    When the tester submits the order for slow validation
    Then the page displays "Validating with the finance system..."
```

### `rec_MT8TEY493Q7L` — Check that adding an item updates the cart badge

`runs/rec_MT8TEY493Q7L/run_001`

| | |
|---|---|
| scenarios | 1 |
| steps | 2 |
| events covered | 4 |
| accepted expected results | 1 |
| grounding rate | 1.0 |
| validator pass (first / final) | 1.0 / 1.0 |
| critic findings raised | 0 |
| tool calls total | 2 |
| tool calls per step | `{'step_002': 1}` |
| rejected by | *nothing* |
| warned by | *nothing* |

```gherkin
# aitc-rem - rec_MT8TEY493Q7L - 2026-08-25 - evidence: tc_rec_MT8TEY493Q7L.trace.md

@cart
Feature: Cart management

  Adding an item to the cart updates the cart badge

  Scenario: Adding an item updates the cart badge
    Given the tester signs in to the application
    When the tester adds a widget to the cart
    Then the cart badge shows "1 items"
```

### `rec_MT8TF0TIMA6U` — Check the cart badge, then that a large order needs approval

`runs/rec_MT8TF0TIMA6U/run_001`

| | |
|---|---|
| scenarios | 1 |
| steps | 4 |
| events covered | 8 |
| accepted expected results | 2 |
| grounding rate | 1.0 |
| validator pass (first / final) | 1.0 / 1.0 |
| critic findings raised | 2 |
| tool calls total | 16 |
| tool calls per step | `{'step_003': 1, 'step_004': 1}` |
| rejected by | *nothing* |
| warned by | *nothing* |

```gherkin
# aitc-rem - rec_MT8TF0TIMA6U - 2026-08-25 - evidence: tc_rec_MT8TF0TIMA6U.trace.md

@checkout @permissions
Feature: Order approval

  Orders exceeding a specific monetary threshold require manual approval

  Scenario: An order exceeding the approval threshold is rejected
    Given the tester signs in to the application
    When the tester adds an item to the cart and proceeds to checkout
    And the tester sets the order total to "900"
    Then the application displays a warning that "Orders over EUR500 require approval"

    When the tester attempts to place the order
    Then the application displays a message indicating that the order requires approval
```

### `rec_MT8TF5SO6S71` — Check that an order over EUR500 requires approval

`runs/rec_MT8TF5SO6S71/run_001`

| | |
|---|---|
| scenarios | 1 |
| steps | 3 |
| events covered | 6 |
| accepted expected results | 1 |
| grounding rate | 1.0 |
| validator pass (first / final) | 1.0 / 1.0 |
| critic findings raised | 0 |
| tool calls total | 2 |
| tool calls per step | `{'step_003': 1}` |
| rejected by | *nothing* |
| warned by | *nothing* |

```gherkin
# aitc-rem - rec_MT8TF5SO6S71 - 2026-08-25 - evidence: tc_rec_MT8TF5SO6S71.trace.md

@orders @permissions
Feature: Order approval

  Orders exceeding a specific monetary threshold require manager approval

  Scenario: An order over EUR500 requires approval
    Given the tester signs in as a user
    When the tester proceeds to checkout
    And the tester sets the order total to an amount over "500" and attempts to place the order
    Then the order is refused with an alert stating "Orders over EUR500 require approval"
```

### `rec_MT8TFEWBYM3L` — Check that an order can be exported after approval

`runs/rec_MT8TFEWBYM3L/abl_A2_rec_MT8TFEWBYM3L`

| | |
|---|---|
| scenarios | 1 |
| steps | 3 |
| events covered | 6 |
| accepted expected results | 1 |
| grounding rate | 1.0 |
| validator pass (first / final) | 1.0 / 1.0 |
| critic findings raised | 0 |
| tool calls total | 2 |
| tool calls per step | `{'step_003': 1}` |
| rejected by | *nothing* |
| warned by | *nothing* |

```gherkin
# aitc-rem - rec_MT8TFEWBYM3L - 2026-08-25 - evidence: tc_rec_MT8TFEWBYM3L.trace.md

@orders @export @needs-review
Feature: Order export

  An order can be exported after it has been approved.

  Scenario: Exporting an order fails with an internal server error
    Given the tester logs in as "<<user_email_1>>"
    When the tester adds a "Blue Widget" to the cart and proceeds to checkout
    And the tester attempts to export the order
    Then the export fails with an "Internal server error"
```

### `rec_MT8TFIOO2A7M` — Check that an order over EUR500 requires approval

`runs/rec_MT8TFIOO2A7M/abl_A2_rec_MT8TFIOO2A7M`

| | |
|---|---|
| scenarios | 1 |
| steps | 3 |
| events covered | 7 |
| accepted expected results | 1 |
| grounding rate | 1.0 |
| validator pass (first / final) | 1.0 / 1.0 |
| critic findings raised | 0 |
| tool calls total | 2 |
| tool calls per step | `{'step_003': 1}` |
| rejected by | *nothing* |
| warned by | *nothing* |

```gherkin
# aitc-rem - rec_MT8TFIOO2A7M - 2026-08-25 - evidence: tc_rec_MT8TFIOO2A7M.trace.md

@orders @approval @needs-review
Feature: Order approval

  Orders exceeding a specific monetary threshold require manager approval.

  Scenario: An order over EUR500 cannot be placed without approval
    Given the tester signs in as a user
    When the tester adds an item to the cart and proceeds to checkout
    And the tester attempts to place an order with a total over "500" EUR
    Then the application displays an alert that "Orders over EUR500 require approval"

    # 2 exploratory action(s) omitted - navigated to reports and back to the catalog. See the review UI.
```

#### Ablation at this point

```json
{
 "table": [
  {
   "config": "A0",
   "recordings": 1,
   "steps": 3,
   "assertions": 0,
   "grounded": 0,
   "ungrounded": 0,
   "groundingRate": 1.0,
   "groundedYield": 0.0,
   "validatorFirstPassRate": 0.7143,
   "validatorFinalPassRate": 0.7143,
   "criticFindings": 0,
   "repairsResolved": 0,
   "repairConvergenceRate": 0.0,
   "toolCalls": 0,
   "toolCallsPerStep": 0.0,
   "effortSpread": 0.0,
   "replayed": 0,
   "executionRate": 0.0,
   "replayAssertions": 0,
   "assertionsHeldRate": 0.0,
   "meanSelectorRank": 0.0,
   "uncachedModelCalls": 0,
   "promptTokens": 2841,
   "durationMs": 36.3,
   "hardFailures": 0
  },
  {
   "config": "A1",
   "recordings": 1,
   "steps": 3,
   "assertions": 2,
   "grounded": 2,
   "ungrounded": 0,
   "groundingRate": 1.0,
   "groundedYield": 0.6667,
   "validatorFirstPassRate": 0.9091,
   "validatorFinalPassRate": 0.9091,
   "criticFindings": 0,
   "repairsResolved": 0,
   "repairConvergenceRate": 0.0,
   "toolCalls": 3,
   "toolCallsPerStep": 1.0,
   "effortSpread": 0.0,
   "replayed": 0,
   "executionRate": 0.0,
   "replayAssertions": 0,
   "assertionsHeldRate": 0.0,
   "meanSelectorRank": 0.0,
   "uncachedModelCalls": 0,
   "promptTokens": 8791,
   "durationMs": 38.2,
   "hardFailures": 0
  },
  {
   "config": "A2",
   "recordings": 1,
   "steps": 3,
   "assertions": 2,
   "grounded": 2,
   "ungrounded": 0,
   "groundingRate": 1.0,
   "groundedYield": 0.6667,
   "validatorFirstPassRate": 0.9091,
   "validatorFinalPassRate": 0.9091,
   "criticFindings": 3,
   "repairsResolved": 2,
   "repairConvergenceRate": 0.6667,
   "toolCalls": 16,
   "toolCallsPerStep": 5.333,
   "effortSpread": 2.5,
   "replayed": 0,
   "executionRate": 0.0,
   "replayAssertions": 0,
   "assertionsHeldRate": 0.0,
   "meanSelectorRank": 0.0,
   "uncachedModelCalls": 11,
   "promptTokens": 37767,
   "durationMs": 126740.6,
   "hardFailures": 0
  }
 ],
 "runs": [
  {
   "config": "A0",
   "recordingId": "rec_MT8TEQCKCCNT",
   "runId": "abl_A0_rec_MT8TEQCKCCNT",
   "runPath": "D:\\files\\Projects\\aitc-rem\\runs\\rec_MT8TEQCKCCNT\\abl_A0_rec_MT8TEQCKCCNT"
  },
  {
   "config": "A1",
   "recordingId": "rec_MT8TEQCKCCNT",
   "runId": "abl_A1_rec_MT8TEQCKCCNT",
   "runPath": "D:\\files\\Projects\\aitc-rem\\runs\\rec_MT8TEQCKCCNT\\abl_A1_rec_MT8TEQCKCCNT"
  },
  {
   "config": "A2",
   "recordingId": "rec_MT8TEQCKCCNT",
   "runId": "abl_A2_rec_MT8TEQCKCCNT",
   "runPath": "D:\\files\\Projects\\aitc-rem\\runs\\rec_MT8TEQCKCCNT\\abl_A2_rec_MT8TEQCKCCNT"
  }
 ],
 "finding": "A0 produced 0 grounded assertion(s) across 3 step(s) (0.00 per step); A2 produced 2 across 3 (0.67 per step). A0 emitted no assertions at all -- it declined to claim rather than fabricating, which is the honest failure mode and the reason grounding RATE must not be read alone: abstaining scores 100% on rate and zero on yield. A2's critic raised 3 finding(s) and the repair loop resolved 2 of 3 within budget (67%). 1 went to the human with the finding stated, which is the designed outcome on exhaustion rather than a failure of the loop. A2's gate went from 91% on the first attempt to 91% after repair (+0%); A1 has no second attempt and sits at 91%. Yield is within 5 points across the two, which is expected rather than disappointing: both arms propose assertions with the same stage and the same tools, so the critic was never going to move it. The columns that separate them are Findings and Converged."
}
```

---

## After — STATUS.md closed, splitter landed — 2026-08-26 15:03 UTC

10 recording(s), newest run of each.

### `rec_MT7MXBS9B2VB` — check if hamper sizes change correctly

`runs/rec_MT7MXBS9B2VB/run_001`

| | |
|---|---|
| scenarios | 2 |
| steps | 4 |
| events covered | 33 |
| accepted expected results | 2 |
| grounding rate | 1.0 |
| validator pass (first / final) | 1.0 / 1.0 |
| critic findings (raised / resolved) | 3 / 3 |
| repair attempts / convergence | 3 / 1.0 |
| tool calls total | 4 |
| tool calls per step | `{'step_003': 0, 'step_004': 0, 'step_002': 0}` |
| scenarios added by the splitter | 1 |
| rejected by | *nothing* |
| warned by | *nothing* |

```gherkin
# aitc-rem - rec_MT7MXBS9B2VB - 2026-08-26 - evidence: tc_rec_MT7MXBS9B2VB_01.trace.md

@hampers
Feature: Hamper size adjustment

  The hamper size automatically upgrades when the number of items exceeds the
  current capacity

  Background:
    Given the tester navigates to the "Create Your Own Hamper" page

  Scenario: A hamper automatically upgrades to a Medium Wicker Basket when capacity is reached
    When the tester adds items to the "Small Wicker Basket" until it reaches capacity
    And the tester increases the quantity of items until the hamper upgrades to a "Medium Wicker Basket"
    Then the hamper is shown as a "Medium Wicker Basket"

    # 1 abandoned action(s) omitted - tester clicked cancel after reaching the maximum hamper size. See the review UI.

# aitc-rem - rec_MT7MXBS9B2VB - 2026-08-26 - evidence: tc_rec_MT7MXBS9B2VB_02.trace.md

@hampers
Feature: Hamper size adjustment

  The hamper size automatically upgrades when the number of items exceeds the
  current capacity

  Background:
    Given the tester navigates to the "Create Your Own Hamper" page

  Scenario: A hamper automatically upgrades to a Large Wicker Basket when capacity is reached
    When the tester increases the item quantity until the "Large Wicker Basket" upgrade is triggered
    Then the hamper is shown as a "Large Wicker Basket"
```

### `rec_MT7VTN7ZRJPO` — Verify that the application enforces the maximum quantity allowed for coffee capsules

`runs/rec_MT7VTN7ZRJPO/run_001`

| | |
|---|---|
| scenarios | 2 |
| steps | 5 |
| events covered | 5 |
| accepted expected results | 1 |
| grounding rate | 1.0 |
| validator pass (first / final) | 0.8 / 0.8888888888888888 |
| critic findings (raised / resolved) | 2 / 1 |
| repair attempts / convergence | 1 / 0.5 |
| tool calls total | 6 |
| tool calls per step | `{'step_003': 1, 'step_004': 1, 'step_001': 1}` |
| scenarios added by the splitter | 0 |
| rejected by | *nothing* |
| warned by | gherkin_style |

```gherkin
# aitc-rem - rec_MT7VTN7ZRJPO - 2026-08-26 - evidence: tc_rec_MT7VTN7ZRJPO.trace.md

@cart @limits
Feature: Shopping cart quantity limits

  Verify that the application enforces the maximum quantity allowed for coffee
  capsules

  Scenario: A user cannot add more than the maximum allowed quantity of a product
    Given the tester is on the coffee capsules page
    When the tester adds items to the shopping bag
    And the tester attempts to add another item beyond the limit
    Then the system prevents the addition of the item and displays an error message indicating the limit has been reached

    When the tester opens the shopping bag
```

### `rec_MTA1O0I78SKF` — Check that an order over EUR500 requires approval

`runs/rec_MTA1O0I78SKF/run_001`

| | |
|---|---|
| scenarios | 1 |
| steps | 5 |
| events covered | 10 |
| accepted expected results | 3 |
| grounding rate | 1.0 |
| validator pass (first / final) | 1.0 / 1.0 |
| critic findings (raised / resolved) | 1 / 0 |
| repair attempts / convergence | 0 / 0.0 |
| tool calls total | 9 |
| tool calls per step | `{'step_003': 0, 'step_004': 6, 'step_005': 0}` |
| scenarios added by the splitter | 0 |
| rejected by | *nothing* |
| warned by | *nothing* |

```gherkin
# aitc-rem - rec_MTA1O0I78SKF - 2026-08-26 - evidence: tc_rec_MTA1O0I78SKF.trace.md

@orders @permissions
Feature: Order approval

  Orders exceeding a specific monetary threshold require manager approval
  before they can be placed

  Scenario: An order over EUR500 requires manager approval
    Given the tester signs in to the application
    When the tester adds an item to the cart and proceeds to checkout
    And the tester sets the order total to "615"
    Then an alert states that orders over EUR500 require approval

    When the tester tries to place the order without approval
    Then the order is rejected with a conflict error

    When the tester confirms manager approval and places the order
    Then the order is confirmed
```

### `rec_MTA1O4R3SSR5` — Exercise the awkward parts of the checkout page

`runs/rec_MTA1O4R3SSR5/run_001`

| | |
|---|---|
| scenarios | 1 |
| steps | 4 |
| events covered | 10 |
| accepted expected results | 2 |
| grounding rate | 1.0 |
| validator pass (first / final) | 0.9166666666666666 / 0.9 |
| critic findings (raised / resolved) | 1 / 0 |
| repair attempts / convergence | 2 / 0.0 |
| tool calls total | 5 |
| tool calls per step | `{'step_003': 0, 'step_004': 0}` |
| scenarios added by the splitter | 0 |
| rejected by | *nothing* |
| warned by | gherkin_style |

```gherkin
# aitc-rem - rec_MTA1O4R3SSR5 - 2026-08-26 - evidence: tc_rec_MTA1O4R3SSR5.trace.md

@checkout @needs-review
Feature: Checkout process

  Exercise the checkout page functionality including shipping, payment, and
  validation

  Scenario: Complete the checkout process with express shipping and payment saving
    Given the tester signs in with email "<<user_email_1>>" and password "<<password>>"
    When the tester navigates to the checkout page and selects "Express (next day, +EUR12)" shipping
    And the tester submits the payment method
    Then the payment method is displayed as saved or selected

    When the tester submits the order for validation
    Then the status "Validating with the finance system..." is displayed
```

### `rec_MTA1OCGA8CPJ` — Check that adding an item updates the cart badge

`runs/rec_MTA1OCGA8CPJ/run_001`

| | |
|---|---|
| scenarios | 1 |
| steps | 2 |
| events covered | 4 |
| accepted expected results | 1 |
| grounding rate | 1.0 |
| validator pass (first / final) | 1.0 / 1.0 |
| critic findings (raised / resolved) | 0 / 0 |
| repair attempts / convergence | 0 / 0.0 |
| tool calls total | 7 |
| tool calls per step | `{'step_002': 6}` |
| scenarios added by the splitter | 0 |
| rejected by | *nothing* |
| warned by | *nothing* |

```gherkin
# aitc-rem - rec_MTA1OCGA8CPJ - 2026-08-26 - evidence: tc_rec_MTA1OCGA8CPJ.trace.md

@cart
Feature: Cart management

  Adding an item to the cart updates the cart badge

  Scenario: Adding an item updates the cart badge
    Given the tester signs in to the application
    When the tester adds a widget to the cart
    Then the cart badge shows "Cart contains 1 items"
```

### `rec_MTA1OF3ND0YN` — Check the cart badge, then that a large order needs approval

`runs/rec_MTA1OF3ND0YN/run_001`

| | |
|---|---|
| scenarios | 2 |
| steps | 3 |
| events covered | 8 |
| accepted expected results | 3 |
| grounding rate | 1.0 |
| validator pass (first / final) | 0.75 / 0.8181818181818182 |
| critic findings (raised / resolved) | 6 / 1 |
| repair attempts / convergence | 3 / 0.16666666666666666 |
| tool calls total | 36 |
| tool calls per step | `{'step_001': 5, 'step_002': 0, 'step_003': 1}` |
| scenarios added by the splitter | 0 |
| rejected by | *nothing* |
| warned by | evidence_discriminates, gherkin_style |

```gherkin
# aitc-rem - rec_MTA1OF3ND0YN - 2026-08-26 - evidence: tc_rec_MTA1OF3ND0YN_01.trace.md

@checkout @permissions
Feature: Order approval

  Orders exceeding a specific monetary threshold require manual approval

  Scenario: An order exceeding the threshold requires approval
    When the tester signs in and adds an item to the cart
    Then The cart badge updates to show 'Cart contains 1 items', confirming the item was successfully added

# aitc-rem - rec_MTA1OF3ND0YN - 2026-08-26 - evidence: tc_rec_MTA1OF3ND0YN_02.trace.md

@checkout @permissions
Feature: Order approval

  Orders exceeding a specific monetary threshold require manual approval

  Background:
    Given the tester signs in and adds an item to the cart

  Scenario: Order requires approval
    When the tester proceeds to checkout and sets the order total to "900"
    Then an alert states that orders over EUR500 require approval

    When the tester tries to place the order
    Then Order requires approval
```

### `rec_MTA1OK3S1NX1` — Check that an order over EUR500 requires approval

`runs/rec_MTA1OK3S1NX1/run_001`

| | |
|---|---|
| scenarios | 1 |
| steps | 3 |
| events covered | 6 |
| accepted expected results | 1 |
| grounding rate | 1.0 |
| validator pass (first / final) | 1.0 / 1.0 |
| critic findings (raised / resolved) | 0 / 0 |
| repair attempts / convergence | 0 / 0.0 |
| tool calls total | 2 |
| tool calls per step | `{'step_003': 0}` |
| scenarios added by the splitter | 0 |
| rejected by | *nothing* |
| warned by | *nothing* |

```gherkin
# aitc-rem - rec_MTA1OK3S1NX1 - 2026-08-26 - evidence: tc_rec_MTA1OK3S1NX1.trace.md

@orders @permissions
Feature: Order approval

  Orders exceeding a specific monetary threshold require manager approval

  Scenario: An order over EUR500 requires manager approval
    Given the tester signs in to the application
    When the tester navigates to the checkout page
    And the tester attempts to place an order with a total over "500"
    Then the order is refused with an alert stating "Orders over EUR500 require approval"
```

### `rec_MTA1OT9OVUZ5` — Check that an order can be exported after approval

`runs/rec_MTA1OT9OVUZ5/run_001`

| | |
|---|---|
| scenarios | 2 |
| steps | 6 |
| events covered | 6 |
| accepted expected results | 2 |
| grounding rate | 1.0 |
| validator pass (first / final) | 1.0 / 1.0 |
| critic findings (raised / resolved) | 1 / 0 |
| repair attempts / convergence | 0 / 0.0 |
| tool calls total | 3 |
| tool calls per step | `{'step_003': 1}` |
| scenarios added by the splitter | 0 |
| rejected by | *nothing* |
| warned by | *nothing* |

```gherkin
# aitc-rem - rec_MTA1OT9OVUZ5 - 2026-08-26 - evidence: tc_rec_MTA1OT9OVUZ5.trace.md

@orders @export
Feature: Order export

  An order can be exported after approval

  Scenario: An order fails to export when the order state is inconsistent
    Given the tester signs in to the application
    When the tester adds a "Blue Widget" to the cart and proceeds to checkout
    And the tester tries to export the order
    Then the export fails with an "Internal server error"
```

### `rec_MTA1OX1AWLOC` — Check that an order over EUR500 requires approval

`runs/rec_MTA1OX1AWLOC/run_001`

| | |
|---|---|
| scenarios | 1 |
| steps | 3 |
| events covered | 7 |
| accepted expected results | 1 |
| grounding rate | 1.0 |
| validator pass (first / final) | 1.0 / 1.0 |
| critic findings (raised / resolved) | 0 / 0 |
| repair attempts / convergence | 0 / 0.0 |
| tool calls total | 2 |
| tool calls per step | `{'step_003': 0}` |
| scenarios added by the splitter | 0 |
| rejected by | *nothing* |
| warned by | *nothing* |

```gherkin
# aitc-rem - rec_MTA1OX1AWLOC - 2026-08-26 - evidence: tc_rec_MTA1OX1AWLOC.trace.md

@orders @permissions
Feature: Order approval

  Orders exceeding a specific value threshold require manual approval

  Scenario: An order over EUR500 requires approval
    Given the tester signs in to the application
    When the tester adds an item to the cart and proceeds to checkout
    And the tester sets the order total to over "500" and attempts to place the order
    Then the order is refused with "Orders over EUR500 require approval"

    # 2 exploratory action(s) omitted - navigated to the reports page and back to the catalogue. See the review UI.
```

### `rec_MTA7A2XHHH22` — check if filters are working correctly

`runs/rec_MTA7A2XHHH22/run_002`

| | |
|---|---|
| scenarios | 2 |
| steps | 7 |
| events covered | 15 |
| accepted expected results | 3 |
| grounding rate | 1.0 |
| validator pass (first / final) | 0.8333333333333334 / 0.8333333333333334 |
| critic findings (raised / resolved) | 0 / 0 |
| repair attempts / convergence | 0 / 0.0 |
| tool calls total | 32 |
| tool calls per step | `{'step_003': 5, 'step_004': 7, 'step_006': 10, 'step_007': 10}` |
| scenarios added by the splitter | 0 |
| rejected by | *nothing* |
| warned by | gherkin_style |

```gherkin
# aitc-rem - rec_MTA7A2XHHH22 - 2026-08-26 - evidence: tc_rec_MTA7A2XHHH22_01.trace.md

@filtering @sorting
Feature: Product filtering

  Verify that product sorting and filtering options correctly update the
  displayed product list

  Background:
    Given the tester is on the "PC Gamer" product category page

  Scenario: Sorting products by price
    When the tester sorts products by "Prix haut à bas"
    And the tester changes the sort order to "Prix bas à haut"

# aitc-rem - rec_MTA7A2XHHH22 - 2026-08-26 - evidence: tc_rec_MTA7A2XHHH22_02.trace.md

@filtering @sorting @needs-review
Feature: Product filtering

  Verify that product sorting and filtering options correctly update the
  displayed product list

  Background:
    Given the tester is on the "PC Gamer" product category page

  Scenario: Filtering products by stock status and processor model
    When the tester filters by "In stock" products
    Then the product list is filtered to show only available items

    When the tester clears the stock filter
    And the tester applies multiple processor model filters
    Then the product list updates to show items matching the selected processors

    When the tester clears all processor filters
    Then the product list updates to show all products
```

#### Ablation at this point

```json
{
 "table": [
  {
   "config": "A0",
   "recordings": 7,
   "steps": 24,
   "assertions": 0,
   "grounded": 0,
   "ungrounded": 0,
   "groundingRate": 1.0,
   "groundedYield": 0.0,
   "validatorFirstPassRate": 0.674,
   "validatorFinalPassRate": 0.674,
   "criticFindings": 0,
   "repairsResolved": 0,
   "repairAttempts": 0,
   "repairConvergenceRate": 0.0,
   "toolCalls": 0,
   "toolCallsPerStep": 0.0,
   "effortSpread": 0.0,
   "replayed": 0,
   "executionRate": 0.0,
   "replayAssertions": 0,
   "assertionsHeldRate": 0.0,
   "meanSelectorRank": 0.0,
   "uncachedModelCalls": 7,
   "promptTokens": 24813,
   "durationMs": 66921.4,
   "hardFailures": 0
  },
  {
   "config": "A1",
   "recordings": 7,
   "steps": 23,
   "assertions": 14,
   "grounded": 14,
   "ungrounded": 0,
   "groundingRate": 1.0,
   "groundedYield": 0.6087,
   "validatorFirstPassRate": 0.9727,
   "validatorFinalPassRate": 0.9727,
   "criticFindings": 0,
   "repairsResolved": 0,
   "repairAttempts": 0,
   "repairConvergenceRate": 0.0,
   "toolCalls": 47,
   "toolCallsPerStep": 2.043,
   "effortSpread": 1.046,
   "replayed": 0,
   "executionRate": 0.0,
   "replayAssertions": 0,
   "assertionsHeldRate": 0.0,
   "meanSelectorRank": 0.0,
   "uncachedModelCalls": 7,
   "promptTokens": 236182,
   "durationMs": 64236.7,
   "hardFailures": 0
  },
  {
   "config": "A2",
   "recordings": 7,
   "steps": 23,
   "assertions": 12,
   "grounded": 12,
   "ungrounded": 0,
   "groundingRate": 1.0,
   "groundedYield": 0.5217,
   "validatorFirstPassRate": 0.9727,
   "validatorFinalPassRate": 1.0,
   "criticFindings": 9,
   "repairsResolved": 1,
   "repairAttempts": 5,
   "repairConvergenceRate": 0.1111,
   "toolCalls": 63,
   "toolCallsPerStep": 2.739,
   "effortSpread": 0.713,
   "replayed": 0,
   "executionRate": 0.0,
   "replayAssertions": 0,
   "assertionsHeldRate": 0.0,
   "meanSelectorRank": 0.0,
   "uncachedModelCalls": 1,
   "promptTokens": 193677,
   "durationMs": 3149.6,
   "hardFailures": 0
  }
 ],
 "runs": [
  {
   "config": "A0",
   "recordingId": "rec_MTA1OCGA8CPJ",
   "runId": "abl_A0_rec_MTA1OCGA8CPJ",
   "runPath": "D:\\files\\Projects\\aitc-rem\\runs\\rec_MTA1OCGA8CPJ\\abl_A0_rec_MTA1OCGA8CPJ"
  },
  {
   "config": "A0",
   "recordingId": "rec_MTA1OT9OVUZ5",
   "runId": "abl_A0_rec_MTA1OT9OVUZ5",
   "runPath": "D:\\files\\Projects\\aitc-rem\\runs\\rec_MTA1OT9OVUZ5\\abl_A0_rec_MTA1OT9OVUZ5"
  },
  {
   "config": "A0",
   "recordingId": "rec_MTA1O0I78SKF",
   "runId": "abl_A0_rec_MTA1O0I78SKF",
   "runPath": "D:\\files\\Projects\\aitc-rem\\runs\\rec_MTA1O0I78SKF\\abl_A0_rec_MTA1O0I78SKF"
  },
  {
   "config": "A0",
   "recordingId": "rec_MTA1O4R3SSR5",
   "runId": "abl_A0_rec_MTA1O4R3SSR5",
   "runPath": "D:\\files\\Projects\\aitc-rem\\runs\\rec_MTA1O4R3SSR5\\abl_A0_rec_MTA1O4R3SSR5"
  },
  {
   "config": "A0",
   "recordingId": "rec_MTA1OK3S1NX1",
   "runId": "abl_A0_rec_MTA1OK3S1NX1",
   "runPath": "D:\\files\\Projects\\aitc-rem\\runs\\rec_MTA1OK3S1NX1\\abl_A0_rec_MTA1OK3S1NX1"
  },
  {
   "config": "A0",
   "recordingId": "rec_MTA1OF3ND0YN",
   "runId": "abl_A0_rec_MTA1OF3ND0YN",
   "runPath": "D:\\files\\Projects\\aitc-rem\\runs\\rec_MTA1OF3ND0YN\\abl_A0_rec_MTA1OF3ND0YN"
  },
  {
   "config": "A0",
   "recordingId": "rec_MTA1OX1AWLOC",
   "runId": "abl_A0_rec_MTA1OX1AWLOC",
   "runPath": "D:\\files\\Projects\\aitc-rem\\runs\\rec_MTA1OX1AWLOC\\abl_A0_rec_MTA1OX1AWLOC"
  },
  {
   "config": "A1",
   "recordingId": "rec_MTA1OCGA8CPJ",
   "runId": "abl_A1_rec_MTA1OCGA8CPJ",
   "runPath": "D:\\files\\Projects\\aitc-rem\\runs\\rec_MTA1OCGA8CPJ\\abl_A1_rec_MTA1OCGA8CPJ"
  },
  {
   "config": "A1",
   "recordingId": "rec_MTA1OT9OVUZ5",
   "runId": "abl_A1_rec_MTA1OT9OVUZ5",
   "runPath": "D:\\files\\Projects\\aitc-rem\\runs\\rec_MTA1OT9OVUZ5\\abl_A1_rec_MTA1OT9OVUZ5"
  },
  {
   "config": "A1",
   "recordingId": "rec_MTA1O0I78SKF",
   "runId": "abl_A1_rec_MTA1O0I78SKF",
   "runPath": "D:\\files\\Projects\\aitc-rem\\runs\\rec_MTA1O0I78SKF\\abl_A1_rec_MTA1O0I78SKF"
  },

```

---
