# `rec_MTA1OT9OVUZ5` — judgement packet

Run: `runs/rec_MTA1OT9OVUZ5/run_001`  ·  set: **dev**  ·  6 recorded events  ·  2 test case(s)

---

## 1 · What the tester said they were doing

**Objective:** Check that an order can be exported after approval

**What the tester marked:**

- `bug_marker` at `t=3036.0`

**Narration:** none.

---

## 2 · What came out

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

---

## 3 · Every step, beside the events it claims and the evidence it reached

### Scenario: An order fails to export when the order state is inconsistent  *(kind: test_case)*

tags: @orders @export

**Given the tester signs in to the application**  `step_001` role=setup
    `evt_001`  input      textbox "Email address"  = "<<user_email_1>>"
    `evt_002`  input      textbox "Password"  = "<<password>>"
    `evt_003`  click      button "Sign in"  -> 200 POST http://localhost:5173/api/login  (rapid_sequence)

**When the tester adds a "Blue Widget" to the cart and proceeds to checkout**  `step_002` role=test_step
    `evt_004`  click      button "Add Blue Widget to cart"  -> 201 POST http://localhost:5173/api/cart
    `evt_005`  click      button "Checkout"

**And the tester tries to export the order**  `step_003` role=test_step
    `evt_006`  click      button "Export the order"  !! 500 POST http://localhost:5173/api/boom  [console error] Uncaught Error: Export failed: order state is inconsistent  (closed_shadow_root)
    **Then** the export fails with an "Internal server error"
        evidence: "Internal server error"  (semantic_node via `tc_0001` at `evt_006`)  provenance=objective

### Scenario: An order fails to export when the order state is inconsistent  *(kind: bug_report)*

tags: @orders @export

**Given the tester signs in to the application**  `bug_step_001` role=setup
    `evt_001`  input      textbox "Email address"  = "<<user_email_1>>"
    `evt_002`  input      textbox "Password"  = "<<password>>"
    `evt_003`  click      button "Sign in"  -> 200 POST http://localhost:5173/api/login  (rapid_sequence)

**When the tester adds a "Blue Widget" to the cart and proceeds to checkout**  `bug_step_002` role=test_step
    `evt_004`  click      button "Add Blue Widget to cart"  -> 201 POST http://localhost:5173/api/cart
    `evt_005`  click      button "Checkout"

**And the tester tries to export the order**  `bug_step_003` role=test_step
    `evt_006`  click      button "Export the order"  !! 500 POST http://localhost:5173/api/boom  [console error] Uncaught Error: Export failed: order state is inconsistent  (closed_shadow_root)
    **Then** the export fails with an "Internal server error"
        evidence: "Internal server error"  (semantic_node via `tc_0001` at `evt_006`)  provenance=objective

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
| tool calls total | `3` |
| tool calls per step | `{'step_003': 1}` |

**Splitter:** `{"decisions": [], "scenariosAdded": 0}`

