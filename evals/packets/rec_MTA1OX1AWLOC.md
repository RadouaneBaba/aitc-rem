# `rec_MTA1OX1AWLOC` — judgement packet

Run: `runs/rec_MTA1OX1AWLOC/run_001`  ·  set: **dev**  ·  9 recorded events  ·  1 test case(s)

---

## 1 · What the tester said they were doing

**Objective:** Check that an order over EUR500 requires approval

**What the tester marked:** nothing. No intent notes, no marked elements, no declared breaks.

**Narration:** none.

---

## 2 · What came out

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

---

## 3 · Every step, beside the events it claims and the evidence it reached

### Scenario: An order over EUR500 requires approval  *(kind: test_case)*

tags: @orders @permissions

**Given the tester signs in to the application**  `step_001` role=setup
    `evt_001`  input      textbox "Email address"  = "<<user_email_1>>"
    `evt_002`  input      textbox "Password"  = "<<password>>"
    `evt_003`  click      button "Sign in"  -> 200 POST http://localhost:5173/api/login  (rapid_sequence)

**When the tester adds an item to the cart and proceeds to checkout**  `step_002` role=test_step
    `evt_006`  click      button "Add Blue Widget to cart"  -> 201 POST http://localhost:5173/api/cart
    `evt_007`  click      button "Checkout"

**And the tester sets the order total to over "500" and attempts to place the order**  `step_003` role=test_step
    `evt_008`  input      spinbutton "Order total (EUR)"  = "750"  (closed_shadow_root)
    `evt_009`  click      button "Place order"  !! 409 POST http://localhost:5173/api/orders  (closed_shadow_root, rapid_sequence)
    **Then** the order is refused with "Orders over EUR500 require approval"
        evidence: "Orders over EUR500 require approval"  (semantic_node via `tc_0001` at `evt_009`)  provenance=objective

**Omitted from this scenario, on purpose:**

- exploratory: navigated to the reports page and back to the catalogue `evt_004`, `evt_005`

---

## 4 · Proposed and refused

*Nothing was proposed and refused.*

---

## 5 · What the gate said

**Rejections:** none

**Warnings:** none

**Critic:** ran, found nothing.

| metric | value |
|---|---|
| assertions accepted | `1` |
| grounding rate | `1.0` |
| validator pass (first) | `1.0` |
| validator pass (final) | `1.0` |
| critic findings raised / resolved | `0 / 0` |
| repair attempts | `0` |
| tool calls total | `2` |
| tool calls per step | `{'step_003': 0}` |

**Splitter:** `{"decisions": [], "scenariosAdded": 0}`

