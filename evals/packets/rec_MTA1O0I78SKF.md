# `rec_MTA1O0I78SKF` — judgement packet

Run: `runs/rec_MTA1O0I78SKF/run_001`  ·  set: **dev**  ·  10 recorded events  ·  1 test case(s)

---

## 1 · What the tester said they were doing

**Objective:** Check that an order over EUR500 requires approval

**What the tester marked:** nothing. No intent notes, no marked elements, no declared breaks.

**Narration:** none.

---

## 2 · What came out

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

---

## 3 · Every step, beside the events it claims and the evidence it reached

### Scenario: An order over EUR500 requires manager approval  *(kind: test_case)*

tags: @orders @permissions

**Given the tester signs in to the application**  `step_001` role=setup
    `evt_001`  input      textbox "Email address"  = "<<user_email_1>>"
    `evt_002`  input      textbox "Password"  = "<<password>>"
    `evt_003`  click      button "Sign in"  -> 200 POST http://localhost:5173/api/login  (rapid_sequence)

**When the tester adds an item to the cart and proceeds to checkout**  `step_002` role=test_step
    `evt_004`  click      button "Add Blue Widget to cart"  -> 201 POST http://localhost:5173/api/cart
    `evt_005`  click      button "Checkout"

**And the tester sets the order total to "615"**  `step_003` role=test_step
    `evt_006`  input      textbox "Purchase order number"  = "PO-4471"  (closed_shadow_root)
    `evt_007`  input      spinbutton "Order total (EUR)"  = "615"  (closed_shadow_root)
    **Then** an alert states that orders over EUR500 require approval
        evidence: "Orders over EUR500 require approval"  (semantic_node via `tc_0001` at `evt_007`)  provenance=objective

**When the tester tries to place the order without approval**  `step_004` role=test_step
    `evt_008`  click      button "Place order"  !! 409 POST http://localhost:5173/api/orders  (closed_shadow_root, rapid_sequence)
    **Then** the order is rejected with a conflict error
        evidence: "{"error":"Orders over EUR500 require approval","code":"APPROVAL_REQUIRED"}"  (network via `tc_0007` at `evt_008`)  provenance=objective

**When the tester confirms manager approval and places the order**  `step_005` role=test_step
    `evt_009`  click      checkbox "Manager approval obtained"  (closed_shadow_root)
    `evt_010`  click      button "Place order"  -> 201 POST http://localhost:5173/api/orders  (closed_shadow_root)
    **Then** the order is confirmed
        evidence: "Order confirmed"  (semantic_node via `tc_0008` at `evt_010`)  provenance=objective

---

## 4 · Proposed and refused

*Nothing was proposed and refused.*

---

## 5 · What the gate said

**Rejections:** none

**Warnings:** none

**Critic findings:**

- `coherence` on `scenario` — 

| metric | value |
|---|---|
| assertions accepted | `3` |
| grounding rate | `1.0` |
| validator pass (first) | `1.0` |
| validator pass (final) | `1.0` |
| critic findings raised / resolved | `1 / 0` |
| repair attempts | `0` |
| tool calls total | `9` |
| tool calls per step | `{'step_003': 0, 'step_004': 6, 'step_005': 0}` |

**Splitter:** `{"decisions": [], "scenariosAdded": 0}`

